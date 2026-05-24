# Outlook for Mac Local-First Inbox Triage (AWS Bedrock Claude)

Local macOS triage tool that automates Outlook for Mac via AppleScript (`osascript`) and classifies emails with AWS Bedrock Claude. No Microsoft Graph or app registration required.

## Safety guarantees
- Default mode is dry-run.
- `--apply` is gated by `ALLOW_APPLY=true` and requires `--confirm-apply "MOVE_EMAILS"`.
- Never deletes, sends, replies, forwards, or marks as read.
- Moves only into `AI Sorted/...` folders (except Inbox keep decisions).
- Low-confidence results are forced to `NEEDS_REVIEW` and kept in Inbox.
- Per-message failures are recorded and do not halt the run.

## Install
```bash
pip install -r requirements.txt
```

## Config
See `.env.example` and set `USER_EMAIL` plus optional `INCLUDE_DIRECT_TO_ME` (default false).

## First safe run
```bash
python -m src.main --dry-run --limit 25
python -m src.main --dry-run --limit 25 --interactive-review
python -m src.main --apply --confirm-apply "MOVE_EMAILS" --interactive-review
```
1. Run dry-run with 25 messages.
2. Inspect `reports/dry_run_report.json` (or `reports/latest.json`).
3. Use interactive review before any move.
4. Apply only with explicit confirm string.

## Commands
```bash
python -m src.main --preflight-only
python -m src.main --dry-run --limit 25
python -m src.main --since-days 7 --unread-only --dry-run
python -m src.main --no-body-preview --dry-run
python -m src.main --max-body-preview-chars 500 --dry-run
python -m src.main --reset-cache --dry-run
```

## Preflight checks
- Outlook automation permission / reachability.
- AWS env/model settings present.
- AWS credentials configured.
- Bedrock model reachable.
- `reports/` writable.

## Notes
- Tool ensures Outlook is running.
- Empty inbox returns cleanly.
- Folder creation is idempotent and supports quoted/slashed names via sanitization.
- Cache file (`.cache/processed_messages.json`) prevents reprocessing same message IDs.
- `reports/latest.json` and `reports/latest.csv` are refreshed each run.
