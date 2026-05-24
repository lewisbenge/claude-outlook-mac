from __future__ import annotations

import argparse
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> None:
        return

from src.bedrock_classifier import BedrockClassifier
from src.cache import ProcessedCache
from src.folder_rules import FolderRuleConfig, choose_target_folder
from src.outlook_client import OutlookClient, OutlookSafetyError
from src.reporting import DecisionLog, write_csv_report, write_json_report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local-first Outlook inbox triage tool")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-body-preview", action="store_true")
    p.add_argument("--max-body-preview-chars", type=int, default=500)
    p.add_argument("--interactive-review", action="store_true")
    p.add_argument("--reset-cache", action="store_true")
    return p


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()
    apply_enabled = os.getenv("ALLOW_APPLY", "false").lower() == "true"
    confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))

    client = OutlookClient(Path("scripts"))
    client.ensure_outlook_running()
    classifier = BedrockClassifier(os.environ["AWS_REGION"], os.environ["BEDROCK_MODEL_ID"])
    cache = ProcessedCache(Path(".cache/processed_messages.json"))
    if args.reset_cache:
        cache.reset()

    messages = client.list_inbox_messages(limit=args.limit, max_body_preview_chars=args.max_body_preview_chars)
    folder_cfg = FolderRuleConfig(root_folder_name="AI Sorted", delete_folder_leaf="Delete")
    existing_folders = client.list_folders()

    decisions: list[DecisionLog] = []
    summary = {"kept_in_inbox": 0, "moved_project": 0, "moved_delete": 0, "needs_review": 0, "failed": 0}

    for m in messages:
        if cache.contains(m.message_id):
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

        result = classifier.classify(meta)
        category = result.category
        target = choose_target_folder(category, result.target_folder, folder_cfg)
        action = "KEEP"

        if result.confidence < confidence_threshold:
            category = "NEEDS_REVIEW"
            target = "Inbox"

        try:
            if category in {"MOVE_TO_PROJECT_FOLDER", "MOVE_TO_DELETE_FOLDER"} and target != "Inbox":
                action = f"MOVE->{target}"
                if args.interactive_review and args.apply:
                    ans = input(f"Move '{m.subject}' to '{target}'? [y/N]: ").strip().lower()
                    if ans not in {"y", "yes"}:
                        action = "SKIPPED_BY_USER"
                        target = "Inbox"
                        category = "NEEDS_REVIEW"
                if target != "Inbox" and target not in existing_folders and args.apply and apply_enabled:
                    client.create_folder(target)
                    existing_folders.add(target)
                if target != "Inbox" and args.apply:
                    client.move_message(m.message_id, target, apply_enabled=apply_enabled)
        except Exception:
            action = "FAILED"
            summary["failed"] += 1

        if category == "KEEP_IN_INBOX":
            summary["kept_in_inbox"] += 1
        elif category == "MOVE_TO_PROJECT_FOLDER" and action.startswith("MOVE->"):
            summary["moved_project"] += 1
        elif category == "MOVE_TO_DELETE_FOLDER" and action.startswith("MOVE->"):
            summary["moved_delete"] += 1
        elif category == "NEEDS_REVIEW":
            summary["needs_review"] += 1

        decisions.append(
            DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, category, result.confidence, target, result.reason, result.needs_user_attention, action)
        )
        cache.add(m.message_id)

    cache.save()
    write_json_report(decisions, Path("reports/dry_run_report.json"))
    write_csv_report(decisions, Path("reports/dry_run_report.csv"))
    print(f"Processed {len(decisions)} messages")
    print(f"Summary: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
