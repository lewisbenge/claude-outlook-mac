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
from src.cache import ProcessedCache, compute_result_hash
from src.folder_rules import FolderRuleConfig, choose_target_folder
from src.outlook_client import OutlookClient
from src.reporting import DecisionLog, NormalizedResult, write_csv_report, write_json_report
from src.triage_engine import (
    ClassificationCache,
    Metrics,
    OperationalMetadataStore,
    classify_batch,
    enrich_deterministic_meta,
    heuristic_classify,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local-first Outlook inbox triage tool")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-body-preview", action="store_true")
    p.add_argument("--max-body-preview-chars", type=int, default=500)
    p.add_argument("--interactive-review", action="store_true")
    p.add_argument("--reset-cache", action="store_true")
    p.add_argument("--reset-processed-cache", action="store_true")
    p.add_argument("--reset-db", action="store_true")
    p.add_argument("--reprocess-all", action="store_true")
    p.add_argument("--ignore-cache", action="store_true")
    p.add_argument("--cache-ttl-hours", type=float, default=None)
    p.add_argument("--preflight-only", action="store_true")
    p.add_argument("--confirm-apply", default="")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--unread-only", action="store_true")
    p.add_argument("--include-direct-to-me", default="false")
    p.add_argument("--debug-json", action="store_true")
    p.add_argument("--claude-timeout-seconds", type=int, default=None)
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
    if args.apply:
        args.dry_run = False
    apply_enabled = os.getenv("ALLOW_APPLY", "false").lower() == "true"
    confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
    include_direct_to_me = str_to_bool(args.include_direct_to_me)
    invite_mode = os.getenv("CALENDAR_INVITE_MODE", "tentative").strip().lower()
    workers = int(os.getenv("CLAUDE_WORKERS", "4"))
    batch_size = int(os.getenv("CLAUDE_BATCH_SIZE", "1"))
    my_email = os.getenv("USER_EMAIL", "")
    debug_pipeline = str_to_bool(os.getenv("DEBUG_PIPELINE", "false"))
    claude_timeout_seconds = args.claude_timeout_seconds if args.claude_timeout_seconds is not None else int(os.getenv("CLAUDE_TIMEOUT_SECONDS", "180"))

    def dlog(msg: str) -> None:
        if debug_pipeline:
            print(f"[DEBUG_PIPELINE] {msg}")
    if args.apply and args.confirm_apply != "MOVE_EMAILS":
        raise RuntimeError('For --apply you must pass --confirm-apply "MOVE_EMAILS" exactly.')

    backend = os.getenv("CLASSIFIER_BACKEND", "claude_cli").strip().lower()
    try:
        client = OutlookClient(Path("scripts"), debug_json=args.debug_json)
    except TypeError:
        client = OutlookClient(Path("scripts"))
    if backend == "claude_cli":
        try:
            classifier = ClaudeCliClassifier(command=os.getenv("CLAUDE_CLI_COMMAND", "claude"), timeout_seconds=claude_timeout_seconds, debug_json=args.debug_json)
        except TypeError:
            classifier = ClaudeCliClassifier(command=os.getenv("CLAUDE_CLI_COMMAND", "claude"), timeout_seconds=claude_timeout_seconds)
    else:
        classifier = BedrockClassifier(os.getenv("AWS_REGION"), os.getenv("BEDROCK_MODEL_ID"))
    run_preflight(client, classifier)
    if args.preflight_only:
        return 0

    client.ensure_outlook_running()
    db_path = Path(".cache/classification_cache.sqlite")
    if args.reset_db and db_path.exists():
        db_path.unlink()
        print(f"[startup] reset-db enabled: removed {db_path}")
    cache = ProcessedCache(Path(".cache/processed_messages.json"))
    class_cache = ClassificationCache(db_path)
    migration_info = class_cache.migrate()
    print(
        f"[startup] schema_version={migration_info['current_version']} "
        f"migrations_applied={migration_info['migrations_applied']}"
    )
    metadata_store = OperationalMetadataStore(db_path)
    metrics = Metrics()
    if args.reset_cache or args.reset_processed_cache:
        cache.reset()
    print(f"[startup] processed_cache_entries={len(cache)}")
    class_cache_entries = 0
    try:
        with class_cache._connect() as con:
            class_cache_entries = int(con.execute("SELECT COUNT(*) FROM classification_cache").fetchone()[0])
    except Exception:
        class_cache_entries = 0
    print(f"[startup] classification_cache_entries={class_cache_entries}")

    classifier_logic_version = os.getenv("CLASSIFIER_LOGIC_VERSION", "1")
    schema_version = str(migration_info["current_version"])
    prompt_version = os.getenv("CLASSIFIER_PROMPT_VERSION", "1")
    current_result_hash = compute_result_hash(
        classifier_logic_version=classifier_logic_version,
        schema_version=schema_version,
        prompt_version=prompt_version,
    )
    messages = client.list_inbox_messages(limit=args.limit, max_body_preview_chars=args.max_body_preview_chars, since_days=args.since_days, unread_only=args.unread_only)
    metrics.c["inbox_messages_retrieved"] = len(messages)

    decisions: list[DecisionLog] = []
    normalized_results: list[NormalizedResult] = []
    summary = {"kept_in_inbox": 0, "moved_project": 0, "moved_delete": 0, "needs_review": 0, "failed": 0}
    folder_cfg = FolderRuleConfig(root_folder_name="AI Sorted", delete_folder_leaf="Delete")
    existing_folders = client.list_folders()

    to_classify = []
    pending_messages = []
    outcome_counts = {"skipped": 0, "heuristics": 0, "cache_hits": 0, "classified": 0, "failed": 0}

    def append_normalized(message, classification: str, action: str, target_folder: str, confidence: float, status: str, reason: str = "", skip_reason: str = "", needs_user_attention: bool = False, parse_error: str = "", raw_response_preview: str = "") -> None:
        normalized_results.append(
            NormalizedResult(
                message_id=message.message_id,
                classification=classification,
                action=action,
                target_folder=target_folder,
                confidence=confidence,
                status=status,
                skip_reason=skip_reason,
                subject=message.subject,
                sender=message.sender,
                recipients=message.recipients,
                cc=message.cc,
                received_at=message.received_at,
                source_folder=message.folder,
                reason=reason,
                parse_error=parse_error,
                raw_response_preview=raw_response_preview,
                needs_user_attention=needs_user_attention,
            )
        )
    for m in messages:
        dlog(f"message_id={m.message_id} lifecycle=retrieved")
        can_use_processed_cache = not args.ignore_cache and not args.reprocess_all
        if can_use_processed_cache and cache.contains(m.message_id, ttl_hours=args.cache_ttl_hours):
            if cache.result_hash(m.message_id) != current_result_hash:
                dlog(f"message_id={m.message_id} lifecycle=reprocess reason=result_hash_changed")
            else:
                metrics.c["skipped_cached_processed"] += 1
                dlog(f"message_id={m.message_id} lifecycle=skipped reason=already_processed_cache")
                outcome_counts["skipped"] += 1
                continue
        if not include_direct_to_me and _is_direct_to_me(m, my_email):
            metrics.c["skipped_direct_to_me"] += 1
            dlog(f"message_id={m.message_id} lifecycle=skipped reason=direct_to_me include_direct_to_me={include_direct_to_me}")
            decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, "KEEP_IN_INBOX", 1.0, "Inbox", "Directly addressed", "", "", True, "KEEP"))
            append_normalized(m, "KEEP_IN_INBOX", "KEEP", "Inbox", 1.0, "skipped", reason="Directly addressed", skip_reason="direct_to_me", needs_user_attention=True)
            outcome_counts["skipped"] += 1
            continue
        meta = {"subject": m.subject, "sender": m.sender, "recipients": m.recipients, "cc": m.cc, "received_at": m.received_at, "folder": m.folder, "body_preview": "" if args.no_body_preview else m.body_preview[:args.max_body_preview_chars]}
        meta = enrich_deterministic_meta(meta)
        dlog(f"message_id={m.message_id} lifecycle=filtered")
        h = heuristic_classify(meta, invite_mode)
        if h:
            metrics.c["heuristic_hits"] += 1
            dlog(f"message_id={m.message_id} lifecycle=heuristic_classification category={h.classification.category}")
            if h.classification.category == "CALENDAR_INVITE":
                metrics.c["invite_hits"] += 1
                if invite_mode == "tentative":
                    client.try_mark_tentative(m.message_id)
            result = h.classification
            target = choose_target_folder(result.category, result.target_folder, folder_cfg)
            decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, result.category, result.confidence, target, result.reason, getattr(result, "parse_error", "") or "", getattr(result, "raw_response_preview", "") or "", result.needs_user_attention, "KEEP" if target == "Inbox" else f"MOVE->{target}"))
            metadata_store.store(m.message_id, meta, result)
            append_normalized(m, result.category, "KEEP" if target == "Inbox" else f"MOVE->{target}", target, result.confidence, "heuristic", reason=result.reason, needs_user_attention=result.needs_user_attention)
            dlog(f"message_id={m.message_id} lifecycle=final_action_generated action={'KEEP' if target == 'Inbox' else f'MOVE->{target}'}")
            outcome_counts["heuristics"] += 1
            continue
        cached = class_cache.lookup(m.sender, m.subject)
        if cached and cached.confidence >= confidence_threshold:
            metrics.c["cache_hits"] += 1
            dlog(f"message_id={m.message_id} lifecycle=cache_classification category={cached.category} confidence={cached.confidence}")
            target = choose_target_folder(cached.category, cached.target_folder, folder_cfg)
            decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, cached.category, cached.confidence, target, "classification cache", "", "", False, "KEEP" if target == "Inbox" else f"MOVE->{target}"))
            metadata_store.store(m.message_id, meta, cached)
            append_normalized(m, cached.category, "KEEP" if target == "Inbox" else f"MOVE->{target}", target, cached.confidence, "cache_hit", reason="classification cache")
            dlog(f"message_id={m.message_id} lifecycle=final_action_generated action={'KEEP' if target == 'Inbox' else f'MOVE->{target}'}")
            outcome_counts["cache_hits"] += 1
            continue
        to_classify.append(meta)
        pending_messages.append(m)
        metrics.c["queued_for_claude"] += 1
        dlog(f"message_id={m.message_id} lifecycle=queued_for_claude")

    classified = classify_batch(classifier, to_classify, workers=workers, batch_size=batch_size, metrics=metrics)
    for m, result in zip(pending_messages, classified):
        dlog(f"message_id={m.message_id} lifecycle=claude_result category={result.category} confidence={result.confidence}")
        meta = enrich_deterministic_meta({"subject": m.subject, "sender": m.sender, "recipients": m.recipients, "cc": m.cc, "received_at": m.received_at, "folder": m.folder, "body_preview": "" if args.no_body_preview else m.body_preview[:args.max_body_preview_chars]})
        target = choose_target_folder(result.category, result.target_folder, folder_cfg)
        if result.confidence < confidence_threshold:
            result.category, target = "NEEDS_REVIEW", "Inbox"
        dlog(f"message_id={m.message_id} lifecycle=final_classification category={result.category} confidence={result.confidence}")
        class_cache.store(m.sender, m.subject, result)
        if result.category == "FAILED":
            outcome_counts["failed"] += 1
        else:
            outcome_counts["classified"] += 1
        decisions.append(DecisionLog(m.message_id, m.subject, m.sender, m.recipients, m.cc, m.received_at, m.folder, result.category, result.confidence, target, result.reason, getattr(result, "parse_error", "") or "", getattr(result, "raw_response_preview", "") or "", result.needs_user_attention, "KEEP" if target == "Inbox" else f"MOVE->{target}"))
        append_normalized(m, result.category, "KEEP" if target == "Inbox" else f"MOVE->{target}", target, result.confidence, "failed" if result.category == "FAILED" else "classified", reason=result.reason, needs_user_attention=result.needs_user_attention, parse_error=getattr(result, "parse_error", "") or "", raw_response_preview=getattr(result, "raw_response_preview", "") or "")
        dlog(f"message_id={m.message_id} lifecycle=final_action_generated action={'KEEP' if target == 'Inbox' else f'MOVE->{target}'}")
        metadata_store.store(m.message_id, meta, result)
        if getattr(result, "project", None):
            metrics.c["extracted_projects"] += 1
        if getattr(result, "action_required", None):
            metrics.c["extracted_actions"] += 1
        if getattr(result, "priority", None):
            metrics.c["inferred_priorities"] += 1

    for d in decisions:
        action_succeeded = True
        if d.target_folder != "Inbox" and d.category in {"MOVE_TO_PROJECT_FOLDER", "MOVE_TO_DELETE_FOLDER"} and args.apply:
            if d.target_folder not in existing_folders and apply_enabled:
                client.create_folder(d.target_folder)
                existing_folders.add(d.target_folder)
            try:
                client.move_message(d.message_id, d.target_folder, apply_enabled=apply_enabled)
            except Exception:
                action_succeeded = False
        if args.apply and not args.dry_run and action_succeeded and d.category != "FAILED":
            cache.add(d.message_id, processing_mode="apply", result_hash=current_result_hash)
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
    write_csv_report(normalized_results, reports_dir / "dry_run_report.csv")
    for row in normalized_results:
        dlog(f"message_id={row.message_id} lifecycle=report_row_written status={row.status}")
    shutil.copyfile(reports_dir / "dry_run_report.json", reports_dir / "latest.json")
    shutil.copyfile(reports_dir / "dry_run_report.csv", reports_dir / "latest.csv")
    metrics.c["final_report_entries"] = len(decisions)
    outcome_skipped = outcome_counts["skipped"]
    outcome_heuristics = outcome_counts["heuristics"]
    outcome_cache_hits = outcome_counts["cache_hits"]
    outcome_classified = outcome_counts["classified"]
    outcome_failed = outcome_counts["failed"]
    outcome_total = outcome_skipped + outcome_heuristics + outcome_cache_hits + outcome_classified + outcome_failed
    if outcome_total != metrics.c["inbox_messages_retrieved"]:
        raise RuntimeError(
            "Invariant violated: total_inbox_messages != skipped + heuristics + cache_hits + classified + failed "
            f"({metrics.c['inbox_messages_retrieved']} != {outcome_skipped} + {outcome_heuristics} + {outcome_cache_hits} + {outcome_classified} + {outcome_failed})"
        )
    if metrics.c["inbox_messages_retrieved"] > 0 and not normalized_results and outcome_skipped != metrics.c["inbox_messages_retrieved"]:
        raise RuntimeError("Invariant violated: emails were retrieved but no normalized results were emitted.")
    if any(r.status == "skipped" and not r.skip_reason for r in normalized_results):
        raise RuntimeError("Invariant violated: skipped emails must include explicit skip_reason.")

    actions_generated = sum(1 for r in normalized_results if r.action != "KEEP")
    dlog(f"pipeline_summary retrieved={metrics.c['inbox_messages_retrieved']} skipped={outcome_skipped} classified={outcome_classified} actions_generated={actions_generated} report_rows_written={len(normalized_results)}")
    print(f"Pipeline Summary: retrieved={metrics.c['inbox_messages_retrieved']} skipped={outcome_skipped} classified={outcome_classified} actions_generated={actions_generated} report_rows_written={len(normalized_results)}")

    print(f"Summary: {summary}")
    print(f"Metrics: {metrics.as_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
