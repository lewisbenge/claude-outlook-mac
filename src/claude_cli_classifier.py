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
    customer_or_org: str | None = None
    routing_source: str | None = None
    operational_class: str | None = None
    action: str | None = None
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
            "You are a JSON API, not a chatbot. Return exactly one JSON object. "
            "Do not include prose, markdown, comments, explanations, or headings. "
            "Your first character must be { and your last character must be }. "
            "Classify each email using schema keys only: category,operational_class,action,target_folder,confidence,needs_user_attention,reason,project,customer_or_org,routing_source. "
            "Allowed operational_class enum: CUSTOMER,PROJECT,TRAVEL,CALENDAR,ADMIN,FINANCE,NEWSLETTER,AUTOMATION,SALES_SPAM,PERSONAL,UNKNOWN. "
            "Policy: KEEP_IN_INBOX only when directly addressed and likely requires action, urgent/time-sensitive response, explicit user task/request, or user named in action context. "
            "If uncertain but not action-required -> category NEEDS_REVIEW and target_folder AI Sorted/Needs Review, not Inbox. "
            "If customer/stakeholder related with no clear project -> category MOVE_TO_CUSTOMER_FOLDER and target_folder AI Sorted/Customers/<customer_or_org>; if customer unknown use AI Sorted/Needs Review. "
            "Travel/booking/flight/car/hotel -> MOVE_TO_TRAVEL_FOLDER target AI Sorted/Travel. "
            "Calendar/meeting invite/update -> MOVE_TO_CALENDAR_FOLDER target AI Sorted/Calendar. "
            "Examples: flight reminder => TRAVEL + AI Sorted/Travel; customer briefing no action => CUSTOMER + AI Sorted/Customers/<org>; direct action request => KEEP_IN_INBOX; newsletter => NEWSLETTER + AI Sorted/Delete; unknown non-action => UNKNOWN + AI Sorted/Needs Review. "
            f"Email: {json.dumps(message)}"
        )
        try:
            text = self._invoke_cli(prompt)
            print(f"Claude CLI raw response (truncated): {repr(text[:500])}")
            try:
                extracted = self._extract_first_json_object(text)
            except Exception:
                extracted = self._extract_wrapped_json(text) or ""
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
                operational_class="UNKNOWN",
                action="MOVE",
                target_folder="AI Sorted/Needs Review",
                confidence=0.0,
                reason=reason,
                needs_user_attention=False,
                parse_error=str(exc),
                raw_response_preview=(f"{preview}\nCLEANED_PREVIEW:{cleaned[:500]}" if cleaned else preview),
            )


    def classify_many(self, messages: list[dict]) -> list[Classification]:
        if len(messages) <= 1:
            return [self.classify(m) for m in messages]
        prompt = (
            "Metadata-first: classify each email metadata item into one category: KEEP_IN_INBOX, "
            "MOVE_TO_PROJECT_FOLDER, MOVE_TO_DELETE_FOLDER, NEEDS_REVIEW, MOVE_TO_CALENDAR_FOLDER. "
            "Return ONLY valid JSON array; every item must include keys: category,operational_class,action,target_folder,confidence,needs_user_attention,reason,project,customer_or_org,routing_source. "
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
