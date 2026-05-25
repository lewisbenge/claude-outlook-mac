from __future__ import annotations

import json
import shutil
import subprocess
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


class ClaudeCliClassifier:
    def __init__(self, command: str = "claude", timeout_seconds: int = 60, debug_json: bool = False) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.debug_json = debug_json

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
        prompt = (
            "Classify the email metadata into one category: KEEP_IN_INBOX, "
            "MOVE_TO_PROJECT_FOLDER, MOVE_TO_DELETE_FOLDER, NEEDS_REVIEW. "
            "Return ONLY valid JSON with keys: category,target_folder,confidence,reason,needs_user_attention. "
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
            print(f"Claude CLI parsing error: {exc}; payload={truncate_payload(locals().get('text', ''))}")
            return Classification(
                category="NEEDS_REVIEW",
                target_folder="Inbox",
                confidence=0.0,
                reason="Model response parsing failed",
                needs_user_attention=True,
            )

    def _invoke_cli(self, prompt: str) -> str:
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
            raise RuntimeError(
                f"Claude CLI not installed or not in PATH: '{self.command}'"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Claude CLI timed out after {self.timeout_seconds}s") from exc

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
