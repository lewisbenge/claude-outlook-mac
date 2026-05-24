from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.bedrock_classifier import BedrockClassifier
from src.folder_rules import FolderRuleConfig, choose_target_folder
from src.outlook_client import OutlookClient, OutlookSafetyError
from src.reporting import DecisionLog, write_csv_report, write_json_report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local-first Outlook inbox triage tool")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    apply_enabled = os.getenv("ALLOW_APPLY", "false").lower() == "true"
    confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))

    client = OutlookClient(Path("scripts"))
    classifier = BedrockClassifier(os.environ["AWS_REGION"], os.environ["BEDROCK_MODEL_ID"])
    messages = client.list_inbox_messages(limit=args.limit)

    folder_cfg = FolderRuleConfig(delete_folder_name=os.getenv("DELETE_FOLDER_NAME", "Delete"))
    existing_folders = client.list_folders()

    decisions: list[DecisionLog] = []

    for m in messages:
        meta = {
            "subject": m.subject,
            "sender": m.sender,
            "recipients": m.recipients,
            "cc": m.cc,
            "received_at": m.received_at,
            "folder": m.folder,
            "body_preview": m.body_preview,
        }
        result = classifier.classify(meta)
        category = result.category
        target = choose_target_folder(category, result.target_folder, folder_cfg)

        if result.confidence < confidence_threshold:
            category = "NEEDS_REVIEW"
            target = "Inbox"

        action = "KEEP"
        if category in {"MOVE_TO_PROJECT_FOLDER", "MOVE_TO_DELETE_FOLDER"} and target != "Inbox":
            action = f"MOVE->{target}"
            if target not in existing_folders and args.apply and apply_enabled:
                client.create_folder(target)
                existing_folders.add(target)
            if args.apply:
                try:
                    client.move_message(m.message_id, target, apply_enabled=apply_enabled)
                except OutlookSafetyError:
                    action = "BLOCKED_BY_SAFETY_GUARD"

        decisions.append(
            DecisionLog(
                message_id=m.message_id,
                subject=m.subject,
                sender=m.sender,
                recipients=m.recipients,
                cc=m.cc,
                received_at=m.received_at,
                source_folder=m.folder,
                category=category,
                confidence=result.confidence,
                target_folder=target,
                reason=result.reason,
                needs_user_attention=result.needs_user_attention,
                action=action,
            )
        )

    write_json_report(decisions, Path("reports/dry_run_report.json"))
    write_csv_report(decisions, Path("reports/dry_run_report.csv"))
    print(f"Processed {len(decisions)} messages. Report at reports/dry_run_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
