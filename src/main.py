from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> None:
        return

from src.bedrock_classifier import BedrockClassifier
from src.cache import ProcessedCache
from src.folder_rules import FolderRuleConfig, choose_target_folder
from src.outlook_client import OutlookClient
from src.reporting import DecisionLog, write_csv_report, write_json_report


def str_to_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local-first Outlook inbox triage tool")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm-apply", type=str, default="")
    p.add_argument("--since-days", type=int, default=-1)
    p.add_argument("--unread-only", action="store_true")
    p.add_argument("--include-direct-to-me", choices=["true", "false"], default=os.getenv("INCLUDE_DIRECT_TO_ME", "false"))
    p.add_argument("--no-body-preview", action="store_true")
    p.add_argument("--max-body-preview-chars", type=int, default=500)
    p.add_argument("--interactive-review", action="store_true")
    p.add_argument("--reset-cache", action="store_true")
    p.add_argument("--preflight-only", action="store_true")
    return p


def run_preflight(client: OutlookClient, classifier: BedrockClassifier) -> None:
    client.preflight_permission_check()
    if not os.getenv("AWS_REGION") or not os.getenv("BEDROCK_MODEL_ID"):
        raise RuntimeError("Missing AWS_REGION or BEDROCK_MODEL_ID")
    if not (os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE") or os.getenv("AWS_WEB_IDENTITY_TOKEN_FILE")):
        raise RuntimeError("AWS credentials are not configured")
    Path("reports").mkdir(parents=True, exist_ok=True)
    testfile = Path("reports/.write_test")
    testfile.write_text("ok", encoding="utf-8")
    testfile.unlink(missing_ok=True)
    classifier.preflight_check()


def _is_direct_to_me(message, my_email: str) -> bool:
    if not my_email:
        return False
    blob = f"{message.recipients} {message.cc}".lower()
    return my_email.lower() in blob


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()
    apply_enabled = os.getenv("ALLOW_APPLY", "false").lower() == "true"
    confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
    include_direct_to_me = str_to_bool(args.include_direct_to_me)
    my_email = os.getenv("USER_EMAIL", "")

    if args.apply and args.confirm_apply != "MOVE_EMAILS":
        raise RuntimeError('For --apply you must pass --confirm-apply "MOVE_EMAILS" exactly.')

    client = OutlookClient(Path("scripts"))
    classifier = BedrockClassifier(os.environ["AWS_REGION"], os.environ["BEDROCK_MODEL_ID"])
    run_preflight(client, classifier)
    if args.preflight_only:
        print("Preflight OK")
        return 0

    client.ensure_outlook_running()
    cache = ProcessedCache(Path(".cache/processed_messages.json"))
    if args.reset_cache:
        cache.reset()

    messages = client.list_inbox_messages(
        limit=args.limit,
        max_body_preview_chars=args.max_body_preview_chars,
        since_days=args.since_days,
        unread_only=args.unread_only,
    )
    folder_cfg = FolderRuleConfig(root_folder_name="AI Sorted", delete_folder_leaf="Delete")
    existing_folders = client.list_folders()

    decisions: list[DecisionLog] = []
    summary = {"kept_in_inbox": 0, "moved_project": 0, "moved_delete": 0, "needs_review": 0, "failed": 0}

    for m in messages:
        if cache.contains(m.message_id):
            continue
        if not include_direct_to_me and _is_direct_to_me(m, my_email):
            decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, "KEEP_IN_INBOX", 1.0, "Inbox", "Directly addressed; skipped per config", True, "KEEP"))
            summary["kept_in_inbox"] += 1
            cache.add(m.message_id)
            continue

        meta = {
            "subject": m.subject,
            "sender": m.sender,
            "recipients": m.recipients,
            "cc": m.cc,
            "received_at": m.received_at,
            "folder": m.folder,
            "body_preview": "" if args.no_body_preview else m.body_preview,
        }

        action = "KEEP"
        try:
            result = classifier.classify(meta)
            category = result.category
            target = choose_target_folder(category, result.target_folder, folder_cfg)
            if result.confidence < confidence_threshold:
                category, target = "NEEDS_REVIEW", "Inbox"

            if category in {"MOVE_TO_PROJECT_FOLDER", "MOVE_TO_DELETE_FOLDER"} and target != "Inbox":
                action = f"MOVE->{target}"
                if args.interactive_review and args.apply:
                    ans = input(f"Move '{m.subject}' to '{target}'? [y/N]: ").strip().lower()
                    if ans not in {"y", "yes"}:
                        category, target, action = "NEEDS_REVIEW", "Inbox", "SKIPPED_BY_USER"
                if target != "Inbox" and args.apply:
                    if target not in existing_folders and apply_enabled:
                        client.create_folder(target)
                        existing_folders.add(target)
                    client.move_message(m.message_id, target, apply_enabled=apply_enabled)

            if category == "KEEP_IN_INBOX":
                summary["kept_in_inbox"] += 1
            elif category == "MOVE_TO_PROJECT_FOLDER" and action.startswith("MOVE->"):
                summary["moved_project"] += 1
            elif category == "MOVE_TO_DELETE_FOLDER" and action.startswith("MOVE->"):
                summary["moved_delete"] += 1
            elif category == "NEEDS_REVIEW":
                summary["needs_review"] += 1

            decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, category, result.confidence, target, result.reason, result.needs_user_attention, action))
            cache.add(m.message_id)
        except Exception as exc:
            summary["failed"] += 1
            decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, "NEEDS_REVIEW", 0.0, "Inbox", f"Failure: {exc}", True, "FAILED"))

    cache.save()
    reports_dir = Path("reports")
    write_json_report(decisions, reports_dir / "dry_run_report.json")
    write_csv_report(decisions, reports_dir / "dry_run_report.csv")
    shutil.copyfile(reports_dir / "dry_run_report.json", reports_dir / "latest.json")
    shutil.copyfile(reports_dir / "dry_run_report.csv", reports_dir / "latest.csv")
    print(f"Processed {len(decisions)} messages")
    print(f"Summary: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
