# Outlook Operational Triage (Open WebUI, Schema-First)

This project is now a schema-first operational triage engine for Outlook on macOS.

## Stable architecture

Outlook -> deterministic preprocessing -> Open WebUI API -> strict schema extraction -> Pydantic validation -> deterministic routing engine -> SQLite cache/memory -> reports/action tracking.

## Safety guarantees (unchanged)

- never delete emails
- never send/reply/forward
- never mark read
- all moves remain under `AI Sorted/...`
- apply mode requires explicit confirmation
- interactive review patterns remain compatible with existing Outlook AppleScript flow

## Configuration

- `OPENWEBUI_BASE_URL`
- `OPENWEBUI_API_KEY`
- `OPENWEBUI_MODEL`

### API usage

- `GET /api/models` preflight model check
- `POST /api/chat/completions` for structured extraction

## Run

```bash
pip install -r requirements.txt
python -m src.main --dry-run
```

Apply mode:

```bash
python -m src.main --apply --confirm-apply MOVE_EMAILS
```

## Reports

Outstanding actions are exported to:

- `reports/outstanding_actions.json`
- `reports/outstanding_actions.csv`
