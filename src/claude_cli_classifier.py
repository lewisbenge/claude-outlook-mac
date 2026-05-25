from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass

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
            "Metadata-first: classify email metadata into one category: KEEP_IN_INBOX, "
            "MOVE_TO_PROJECT_FOLDER, MOVE_TO_DELETE_FOLDER, NEEDS_REVIEW. "
            "Return ONLY valid JSON with keys: category,target_folder,confidence,reason,needs_user_attention,project,organization,stakeholders,action_required,priority,topics,meeting_related,contains_decision,contains_tasking,short_summary. "
            "Do not include markdown. Do not include explanation text. "
            f"Email: {json.dumps(message)}"
        )
        try:
            text = self._invoke_cli(prompt)
            print(f"Claude CLI raw response (truncated): {repr(text[:500])}")
            extracted = self._extract_first_json_object(text)
            sanitized = sanitize_control_chars(extracted)
            data = safe_json_loads(sanitized, context="claude_cli.extracted_json", default={}, debug_json=self.debug_json)
            return Classification(**data)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"Claude CLI parsing error: {exc}; payload={truncate_payload(locals().get('text', ''))}")
            reason = "Model response parsing failed"
            if "timed out" in str(exc).lower():
                reason = f"Claude timeout: {exc}"
            return Classification(
                category="NEEDS_REVIEW",
                target_folder="Inbox",
                confidence=0.0,
                reason=reason,
                needs_user_attention=True,
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

    _extract_first_json_object = staticmethod(BedrockClassifier._extract_first_json_object)
