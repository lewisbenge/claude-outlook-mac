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
from src.claude_cli_classifier import ClaudeCliClassifier
from src.cache import ProcessedCache
from src.folder_rules import FolderRuleConfig, choose_target_folder
from src.outlook_client import OutlookClient
from src.reporting import DecisionLog, write_csv_report, write_json_report
from src.triage_engine import ClassificationCache, Metrics, classify_batch, heuristic_classify


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local-first Outlook inbox triage tool")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-body-preview", action="store_true")
    p.add_argument("--max-body-preview-chars", type=int, default=500)
    p.add_argument("--interactive-review", action="store_true")
    p.add_argument("--reset-cache", action="store_true")
    p.add_argument("--preflight-only", action="store_true")
    p.add_argument("--confirm-apply", default="")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--unread-only", action="store_true")
    p.add_argument("--include-direct-to-me", default="false")
    p.add_argument("--debug-json", action="store_true")
    return p


def str_to_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def run_preflight(client: OutlookClient, classifier) -> None:
    report = client.preflight_permission_check()
    if report is None:
        raise RuntimeError("Outlook preflight failed: no preflight report was returned")
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
    invite_mode = os.getenv("CALENDAR_INVITE_MODE", "tentative").strip().lower()
    workers = int(os.getenv("CLAUDE_WORKERS", "4"))
    batch_size = int(os.getenv("CLAUDE_BATCH_SIZE", "4"))
    my_email = os.getenv("USER_EMAIL", "")
    if args.apply and args.confirm_apply != "MOVE_EMAILS":
        raise RuntimeError('For --apply you must pass --confirm-apply "MOVE_EMAILS" exactly.')

    backend = os.getenv("CLASSIFIER_BACKEND", "claude_cli").strip().lower()
    try:
        client = OutlookClient(Path("scripts"), debug_json=args.debug_json)
    except TypeError:
        client = OutlookClient(Path("scripts"))
    if backend == "claude_cli":
        try:
            classifier = ClaudeCliClassifier(command=os.getenv("CLAUDE_CLI_COMMAND", "claude"), debug_json=args.debug_json)
        except TypeError:
            classifier = ClaudeCliClassifier(command=os.getenv("CLAUDE_CLI_COMMAND", "claude"))
    else:
        classifier = BedrockClassifier(os.getenv("AWS_REGION"), os.getenv("BEDROCK_MODEL_ID"))
    run_preflight(client, classifier)
    if args.preflight_only:
        return 0

    client.ensure_outlook_running()
    cache = ProcessedCache(Path(".cache/processed_messages.json"))
    class_cache = ClassificationCache(Path(".cache/classification_cache.sqlite"))
    metrics = Metrics()
    if args.reset_cache:
        cache.reset()
    messages = client.list_inbox_messages(limit=args.limit, max_body_preview_chars=args.max_body_preview_chars, since_days=args.since_days, unread_only=args.unread_only)

    decisions: list[DecisionLog] = []
    summary = {"kept_in_inbox": 0, "moved_project": 0, "moved_delete": 0, "needs_review": 0, "failed": 0}
    folder_cfg = FolderRuleConfig(root_folder_name="AI Sorted", delete_folder_leaf="Delete")
    existing_folders = client.list_folders()

    to_classify = []
    pending_messages = []
    for m in messages:
        if cache.contains(m.message_id):
            continue
        if not include_direct_to_me and _is_direct_to_me(m, my_email):
            metrics.c["skipped_direct_to_me"] += 1
            decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, "KEEP_IN_INBOX", 1.0, "Inbox", "Directly addressed", True, "KEEP"))
            cache.add(m.message_id)
            continue
        meta = {"subject": m.subject, "sender": m.sender, "recipients": m.recipients, "cc": m.cc, "received_at": m.received_at, "folder": m.folder, "body_preview": "" if args.no_body_preview else m.body_preview[:args.max_body_preview_chars]}
        h = heuristic_classify(meta, invite_mode)
        if h:
            metrics.c["heuristic_hits"] += 1
            if h.classification.category == "CALENDAR_INVITE":
                metrics.c["invite_handling_count"] += 1
                if invite_mode == "tentative":
                    client.try_mark_tentative(m.message_id)
            result = h.classification
            target = choose_target_folder(result.category, result.target_folder, folder_cfg)
            decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, result.category, result.confidence, target, result.reason, result.needs_user_attention, "KEEP" if target == "Inbox" else f"MOVE->{target}"))
            cache.add(m.message_id)
            continue
        cached = class_cache.lookup(m.sender, m.subject)
        if cached and cached.confidence >= confidence_threshold:
            metrics.c["cache_hits"] += 1
            target = choose_target_folder(cached.category, cached.target_folder, folder_cfg)
            decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, cached.category, cached.confidence, target, "classification cache", False, "KEEP" if target == "Inbox" else f"MOVE->{target}"))
            cache.add(m.message_id)
            continue
        to_classify.append(meta)
        pending_messages.append(m)

    classified = classify_batch(classifier, to_classify, workers=workers, batch_size=batch_size, metrics=metrics)
    for m, result in zip(pending_messages, classified):
        target = choose_target_folder(result.category, result.target_folder, folder_cfg)
        if result.confidence < confidence_threshold:
            result.category, target = "NEEDS_REVIEW", "Inbox"
        class_cache.store(m.sender, m.subject, result)
        decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, result.category, result.confidence, target, result.reason, result.needs_user_attention, "KEEP" if target == "Inbox" else f"MOVE->{target}"))
        cache.add(m.message_id)

    for d in decisions:
        if d.target_folder != "Inbox" and d.category in {"MOVE_TO_PROJECT_FOLDER", "MOVE_TO_DELETE_FOLDER"} and args.apply:
            if d.target_folder not in existing_folders and apply_enabled:
                client.create_folder(d.target_folder)
                existing_folders.add(d.target_folder)
            try:
                client.move_message(d.message_id, d.target_folder, apply_enabled=apply_enabled)
            except Exception:
                pass
        if d.category in {"KEEP_IN_INBOX", "CALENDAR_INVITE"}:
            summary["kept_in_inbox"] += 1
        elif d.category == "MOVE_TO_PROJECT_FOLDER":
            summary["moved_project"] += 1
        elif d.category == "MOVE_TO_DELETE_FOLDER":
            summary["moved_delete"] += 1
        elif d.category == "NEEDS_REVIEW":
            summary["needs_review"] += 1

    cache.save()
    reports_dir = Path("reports")
    write_json_report(decisions, reports_dir / "dry_run_report.json")
    write_csv_report(decisions, reports_dir / "dry_run_report.csv")
    shutil.copyfile(reports_dir / "dry_run_report.json", reports_dir / "latest.json")
    shutil.copyfile(reports_dir / "dry_run_report.csv", reports_dir / "latest.csv")
    print(f"Summary: {summary}")
    print(f"Metrics: {metrics.as_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
