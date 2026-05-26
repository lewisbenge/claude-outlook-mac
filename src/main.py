from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.openwebui_classifier import EmailInput, OpenWebUIClassifier
from src.outlook_client import OutlookClient
from src.routing import determine_routing


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm-apply", default="")
    p.add_argument("--max-body-preview-chars", type=int, default=500)
    p.add_argument("--preflight-only", action="store_true")
    return p


def write_action_reports(rows: list[dict]) -> None:
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    (reports_dir / "outstanding_actions.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if rows:
        fields = sorted({k for r in rows for k in r})
        with (reports_dir / "outstanding_actions.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)


REPO_ROOT = Path(__file__).resolve().parent.parent


def initialize_environment(repo_root: Path | None = None) -> None:
    root = repo_root or REPO_ROOT
    dotenv_path = root / ".env"
    env_found = load_dotenv(dotenv_path=dotenv_path)
    print(f"[startup] .env file found: {env_found}")
    print(f"[startup] OPENWEBUI_BASE_URL set: {bool(os.getenv('OPENWEBUI_BASE_URL'))}")
    print(f"[startup] OPENWEBUI_MODEL set: {bool(os.getenv('OPENWEBUI_MODEL'))}")
    print(f"[startup] OPENWEBUI_API_KEY set: {bool(os.getenv('OPENWEBUI_API_KEY'))}")


def main() -> int:
    initialize_environment()
    args = build_parser().parse_args()
    if args.apply and args.confirm_apply != "MOVE_EMAILS":
        raise RuntimeError('For --apply you must pass --confirm-apply "MOVE_EMAILS" exactly.')

    classifier = OpenWebUIClassifier()
    client = OutlookClient(Path("scripts"))
    client.preflight_permission_check()
    classifier.preflight_check()
    if args.preflight_only:
        return 0

    messages = client.list_inbox_messages(limit=args.limit, max_body_preview_chars=args.max_body_preview_chars, since_days=30, unread_only=False)
    actions = []
    for m in messages:
        ctx, retried = classifier.classify(EmailInput(subject=m.subject, sender=m.sender, recipients=m.recipients, cc=m.cc, body_preview=m.body_preview[: args.max_body_preview_chars]))
        decision = determine_routing(ctx)
        parse_success = True
        row = {
            "message_id": m.message_id,
            "operational_class": ctx.operational_class,
            "customer_or_org": ctx.customer_or_org,
            "project": ctx.project,
            "confidence": ctx.confidence,
            "action": decision.action,
            "target_folder": decision.target_folder,
            "routing_source": decision.routing_source,
            "parse_success": parse_success,
            "schema_validation_success": True,
            "needs_user_attention": ctx.needs_user_attention,
            "waiting_on_me": ctx.waiting_on_me,
            "follow_up_required": ctx.follow_up_required,
            "urgency": ctx.urgency,
            "action_summary": ctx.action_summary,
            "retry_on_invalid_schema": retried,
        }
        actions.append(row)
        if args.apply and decision.action == "MOVE" and decision.target_folder.startswith("AI Sorted/"):
            client.move_message(m.message_id, decision.target_folder)

    write_action_reports([r for r in actions if r.get("waiting_on_me") or r.get("follow_up_required")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
