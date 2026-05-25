from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import codecs
from dataclasses import dataclass
from pathlib import Path

from src.bedrock_classifier import BedrockClassifier
from src.json_utils import safe_json_loads, sanitize_control_chars, truncate_payload


@dataclass
class Classification:
    category: str
    target_folder: str
    confidence: float
    reason: str
    needs_user_attention: bool
    project: str | None = None
    organization: str | None = None
    stakeholders: list[str] | None = None
    action_required: bool | None = None
    priority: str | None = None
    topics: list[str] | None = None
    meeting_related: bool | None = None
    contains_decision: bool | None = None
    contains_tasking: bool | None = None
    short_summary: str | None = None
    parse_error: str | None = None
    raw_response_preview: str | None = None


class ClaudeCliClassifier:
    def __init__(self, command: str = "claude", timeout_seconds: int = 180, debug_json: bool = False) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.debug_json = debug_json
        self.last_latency_seconds: float | None = None
        self.last_error: str | None = None

    def preflight_check(self) -> None:
        executable = shutil.which(self.command)
        if not executable:
            raise RuntimeError(
                f"Claude CLI not found: command='{self.command}'. Install Claude CLI or set CLAUDE_CLI_COMMAND."
            )
        print(f"Claude CLI preflight: command={self.command}, executable={executable}")
        probe = self._invoke_cli('Respond ONLY with JSON: {"ok": true}')
        extracted = self._extract_first_json_object(probe)
        parsed = safe_json_loads(extracted, context="claude_cli.preflight", default={}, debug_json=self.debug_json)
        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            raise RuntimeError(
                "Claude CLI preflight failed: test prompt did not return expected JSON. "
                "Authentication may be expired or CLI output mode is incompatible."
            )

    def classify(self, message: dict) -> Classification:
        self.last_error = None
        prompt = (
            "Metadata-first. First classify intent into one of: PROJECT,CUSTOMER,TRAVEL,CALENDAR,ADMIN,FINANCE,NEWSLETTER,AUTOMATION,PERSONAL,UNKNOWN. "
            "Operational/admin/travel beats project inference. Do not overuse prior project memory. Infer project only with strong evidence. "
            "Negative examples: Flight booking != project. Calendar reminder != project. Generic corporate announcement != project. "
            "Then choose category: KEEP_IN_INBOX, MOVE_TO_PROJECT_FOLDER, MOVE_TO_CUSTOMER_FOLDER, MOVE_TO_DELETE_FOLDER, MOVE_TO_TRAVEL_FOLDER, MOVE_TO_CALENDAR_FOLDER, MOVE_TO_FINANCE_FOLDER, MOVE_TO_NEWSLETTER_FOLDER, NEEDS_REVIEW. "
            "Output format is strict and mandatory: output must start with BEGIN_JSON on its own line, "
            "then exactly one JSON object with keys: category,target_folder,confidence,reason,needs_user_attention,project,organization,stakeholders,action_required,priority,topics,meeting_related,contains_decision,contains_tasking,short_summary, "
            "then END_JSON on its own line. No markdown. No explanation. No extra text. "
            f"Email: {json.dumps(message)}"
        )
        try:
            text = self._invoke_cli(prompt)
            print(f"Claude CLI raw response (truncated): {repr(text[:500])}")
            extracted = self._extract_wrapped_json(text) or self._extract_first_json_object(text)
            sanitized = sanitize_control_chars(extracted)
            data = safe_json_loads(sanitized, context="claude_cli.extracted_json", default={}, debug_json=self.debug_json)
            if not isinstance(data, dict) or "category" not in data:
                raise ValueError("Claude response JSON did not parse into expected object")
            data.setdefault("parse_error", None)
            data.setdefault("raw_response_preview", text[:500])
            return Classification(**data)
        except Exception as exc:
            self.last_error = str(exc)
            raw = locals().get("text", "")
            cleaned = locals().get("sanitized", "")
            preview = raw[:500]
            print(f"Claude CLI parsing error: {exc}; payload={truncate_payload(raw)}")
            if cleaned:
                self._write_parse_failure_debug(raw=raw, cleaned=cleaned, error=str(exc))
            reason = "Model response parsing failed"
            if "timed out" in str(exc).lower():
                reason = f"Claude timeout: {exc}"
            elif self._has_obvious_classification_hints(raw):
                reason = "Model response parsing failed (natural language hints detected)"
            return Classification(
                category="NEEDS_REVIEW",
                target_folder="Inbox",
                confidence=0.0,
                reason=reason,
                needs_user_attention=True,
                parse_error=str(exc),
                raw_response_preview=(f"{preview}\nCLEANED_PREVIEW:{cleaned[:500]}" if cleaned else preview),
            )


    def classify_many(self, messages: list[dict]) -> list[Classification]:
        if len(messages) <= 1:
            return [self.classify(m) for m in messages]
        prompt = (
            "Metadata-first: classify each email metadata item into one category: KEEP_IN_INBOX, "
            "MOVE_TO_PROJECT_FOLDER, MOVE_TO_DELETE_FOLDER, NEEDS_REVIEW, CALENDAR_INVITE. "
            "Return ONLY valid JSON array; every item must include keys: category,target_folder,confidence,reason,needs_user_attention,project,organization,stakeholders,action_required,priority,topics,meeting_related,contains_decision,contains_tasking,short_summary. "
            f"Emails: {json.dumps(messages)}"
        )
        try:
            text = self._invoke_cli(prompt)
            extracted = self._extract_first_json_object(text)
            data = safe_json_loads(sanitize_control_chars(extracted), context="claude_cli.batch", default=[], debug_json=self.debug_json)
            if not isinstance(data, list):
                raise ValueError("batch response is not list")
            return [Classification(**item) for item in data]
        except Exception:
            return [self.classify(m) for m in messages]
    def _invoke_cli(self, prompt: str) -> str:
        t0 = time.perf_counter()
        try:
            result = subprocess.run(
                [self.command],
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            self.last_latency_seconds = time.perf_counter() - t0
            raise RuntimeError(
                f"Claude CLI not installed or not in PATH: '{self.command}'"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            self.last_latency_seconds = time.perf_counter() - t0
            raise RuntimeError(f"Claude CLI timed out after {self.timeout_seconds}s") from exc

        self.last_latency_seconds = time.perf_counter() - t0
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        self._write_raw_debug(stdout, stderr)
        if result.returncode != 0:
            err_text = f"Claude CLI failed (exit={result.returncode}): {truncate_payload(stderr or stdout)}"
            low = (stderr + "\n" + stdout).lower()
            if "auth" in low or "login" in low or "expired" in low:
                raise RuntimeError(
                    "Claude CLI authentication appears invalid/expired. Run `claude login` and retry. "
                    + err_text
                )
            raise RuntimeError(err_text)
        return stdout

    @staticmethod
    def _extract_wrapped_json(text: str) -> str | None:
        start_marker = "BEGIN_JSON"
        end_marker = "END_JSON"
        if start_marker not in text or end_marker not in text:
            return None
        start = text.find(start_marker) + len(start_marker)
        end = text.find(end_marker, start)
        if end < 0:
            return None
        return ClaudeCliClassifier._unescape_wrapped_payload(text[start:end].strip())

    @staticmethod
    def _unescape_wrapped_payload(payload: str) -> str:
        if not payload:
            return payload
        try:
            if "\\n" in payload or "\\r" in payload or "\\t" in payload or '\\"' in payload:
                return codecs.decode(payload, "unicode_escape")
        except Exception:
            return (
                payload.replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace("\\t", "\t")
                .replace('\\"', '"')
            )
        return payload

    @staticmethod
    def _has_obvious_classification_hints(text: str) -> bool:
        low = (text or "").lower()
        hints = [
            "needs_review",
            "keep_in_inbox",
            "move_to_project_folder",
            "move_to_delete_folder",
            "needs review",
            "keep in inbox",
            "move to project",
            "move to delete",
        ]
        return any(h in low for h in hints)

    def _write_raw_debug(self, stdout: str, stderr: str) -> None:
        if os.getenv("DEBUG_CLAUDE_RAW", "").strip().lower() != "true":
            return
        ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        path = Path("debug") / f"claude_raw_{ts}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n", encoding="utf-8")

    def _write_parse_failure_debug(self, *, raw: str, cleaned: str, error: str) -> None:
        ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        path = Path("debug") / f"claude_parse_failure_{ts}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"ERROR:\n{error}\n\nRAW:\n{raw}\n\nCLEANED:\n{cleaned}\n", encoding="utf-8")

    _extract_first_json_object = staticmethod(BedrockClassifier._extract_first_json_object)
