# Outlook for Mac Local-First Inbox Triage (AWS Bedrock Claude)

Local macOS triage tool that automates Outlook for Mac via AppleScript (`osascript`) and classifies emails with AWS Bedrock Claude. No Microsoft Graph or app registration required.

## Safety guarantees
- Default mode is dry-run.
- `--apply` is gated by `ALLOW_APPLY=true`.
- Never deletes, sends, replies, forwards, or marks as read.
- Moves only into `AI Sorted/...` folders (except Inbox keep decisions).
- Low-confidence results are forced to `NEEDS_REVIEW` and kept in Inbox.

## Install
```bash
pip install -r requirements.txt
```

## Config
See `.env.example`.

## Commands
```bash
python -m src.main --dry-run
python -m src.main --limit 50 --dry-run
python -m src.main --no-body-preview --dry-run
python -m src.main --max-body-preview-chars 500 --dry-run
python -m src.main --interactive-review --apply
python -m src.main --reset-cache --dry-run
```

## Automation permissions
Enable macOS Automation permission for your terminal app to control Microsoft Outlook.

## Notes
- Tool ensures Outlook is running.
- Empty inbox returns cleanly.
- Folder creation is idempotent and supports quoted/slashed names via sanitization.
- Cache file (`.cache/processed_messages.json`) prevents reprocessing same message IDs.
