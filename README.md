# Outlook for Mac Local-First Inbox Triage (Claude CLI + Optional AWS Bedrock)

This tool classifies Inbox mail using Claude CLI (default) or AWS Bedrock (optional), and moves messages with Outlook for Mac automation (`osascript` + AppleScript). It does not use Microsoft Graph or app registration.

## Why Graph API is not used

Enterprise constraints can block app registration/token issuance. This project automates the installed Outlook for Mac client locally via AppleScript.

## Safety model

- Default behavior is **dry-run**.
- `--apply` is supported but blocked unless `ALLOW_APPLY=true`.
- No send/reply/forward/delete endpoints are implemented.
- Full email bodies are not logged.
- Low-confidence items are forced to `NEEDS_REVIEW` and kept in Inbox.

## Project layout

- `src/main.py`
- `src/outlook_client.py`
- `src/claude_cli_classifier.py`
- `src/bedrock_classifier.py`
- `src/folder_rules.py`
- `src/reporting.py`
- `scripts/outlook_list_messages.applescript`
- `scripts/outlook_move_message.applescript`
- `.env.example`
- `tests/`

## Setup

1. Install Python 3.11+
2. Install dependencies:
   ```bash
   pip install pytest python-dotenv
   ```
3. Copy `.env.example` to `.env` and fill values.
4. Configure AWS credentials for Bedrock (`aws configure` or environment variables).
5. Open Outlook for Mac and sign in.

## macOS Automation permissions

1. First run prompts for **Automation** permission.
2. In **System Settings → Privacy & Security → Automation**, allow Terminal/iTerm (or your runner) to control Microsoft Outlook.
3. If blocked, remove permissions and rerun to re-prompt.



## Classifier backend configuration

Default backend is Claude CLI:

```bash
export CLASSIFIER_BACKEND=claude_cli
export CLAUDE_CLI_COMMAND=claude
python -m src.main --dry-run
```

Preflight validates the CLI executable and runs a lightweight JSON probe prompt.
If auth is expired, run `claude login` and retry.


### Claude CLI tuning

For slower or larger prompts, tune timeout and batching:

```bash
export CLAUDE_TIMEOUT_SECONDS=180
export CLAUDE_BATCH_SIZE=1
python -m src.main --dry-run --no-body-preview
```

- `CLAUDE_TIMEOUT_SECONDS` (default `180`) controls per-call Claude CLI timeout.
- `CLAUDE_BATCH_SIZE` (default `1`) is the safest Claude CLI concurrency chunking default.
- `--no-body-preview` reduces payload size and can lower timeout risk.

You can also override timeout on a single run:

```bash
python -m src.main --dry-run --claude-timeout-seconds 240
```


## Bedrock model configuration

When using Bedrock, set `CLASSIFIER_BACKEND=bedrock` and configure model invocation:

```bash
export CLASSIFIER_BACKEND=bedrock
export AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
python -m src.main --dry-run
```

If your Claude model must be invoked via an inference profile, set `BEDROCK_INFERENCE_PROFILE_ARN`.
When this value is set, the tool invokes Bedrock with the profile ARN instead of direct model ID:

```bash
export AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=anthropic.claude-3-7-sonnet-20250219-v1:0
export BEDROCK_INFERENCE_PROFILE_ARN=arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-3-7-sonnet-20250219-v1:0
python -m src.main --dry-run
```

Preflight now validates invocation mode and prints active Bedrock target settings.
If on-demand invocation is unsupported, it explains how to switch to an inference profile ARN.

## Run

Dry-run (recommended):
```bash
python -m src.main --dry-run
python -m src.main --limit 50 --dry-run
```

Apply mode (explicitly gated):
```bash
export ALLOW_APPLY=true
python -m src.main --apply
```

## Risks and limitations

- Outlook AppleScript support varies by Outlook version/channel.
- Message identifiers and folder APIs may behave differently across tenants/profiles.
- AppleScript interactions are slower and less resilient than server-side APIs.
- Body preview availability is inconsistent; tool uses metadata-first classification.

## Report review

After each run, inspect:

- `reports/dry_run_report.json`
- `reports/dry_run_report.csv`

Validate proposed moves before enabling `--apply`.

## Desktop foundation (Tauri + React + local Python agent)

This repository now includes a **local-first desktop scaffold** without replacing the existing inbox engine.

### Added architecture layers

- `desktop-ui/`: Tauri v2 + React/TypeScript shell (chat/task/inbox sidebar UX).
- `src/desktop_api.py`: local IPC/API (HTTP on `127.0.0.1:8765`) for frontend-to-agent communication.
- `src/ops_service.py`: tool-driven runtime with:
  - tool registry (`inbox_triage`, `classify_email`, `move_email`, `create_folder`, `tentative_calendar_response`, `generate_digest`)
  - task orchestration primitives (queued/running/completed)
  - streaming events model scaffold (`/events` SSE)
  - operational memory expansion in SQLite (`thread_memory` metadata)

### Safety guarantees preserved

The original constraints are unchanged:
- never delete messages
- never send/reply/forward
- never mark read
- non-Inbox sorting remains under `AI Sorted/...`
- `apply` still requires explicit user intent
- interactive review workflow remains compatible with existing CLI pipeline

### Developer setup (desktop foundation)

1. Install Python deps:
   ```bash
   pip install -r requirements.txt
   ```
2. Start local backend service:
   ```bash
   python -m src.desktop_api
   ```
3. In another terminal, run desktop frontend:
   ```bash
   cd desktop-ui
   npm install
   npm run tauri dev
   ```

### Notes

- This is a **foundation** for future MCP/tool capability exposure, not a full MCP implementation.
- Existing `python -m src.main` inbox-cleaning flow is intentionally retained.
