from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.json_utils import safe_json_loads


@dataclass
class OutlookMessage:
    message_id: str
    subject: str
    sender: str
    recipients: str
    cc: str
    received_at: str
    folder: str
    body_preview: str


class OutlookSafetyError(RuntimeError):
    pass


@dataclass
class PreflightReport:
    automation_access: str
    inbox_access: str
    folder_enumeration: str
    folder_create: str
    move_support: str
    warnings: list[str]
    status: str


class OutlookClient:
    def __init__(self, scripts_dir: Path, debug_json: bool = False) -> None:
        self.scripts_dir = scripts_dir
        self.preflight_report: PreflightReport | None = None
        self.debug_json = debug_json

    def _run_script(self, script_name: str, *args: str) -> str:
        script_path = self.scripts_dir / script_name
        result = subprocess.run(
            ["osascript", str(script_path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        raw = result.stdout or ""
        logging.debug("AppleScript raw output [%s]: %r", script_name, raw[:500])
        return self._sanitize_applescript_output(raw).strip()

    @staticmethod
    def _sanitize_applescript_output(text: str) -> str:
        cleaned = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        cleaned = re.sub(r"[\ud800-\udfff]", "", cleaned)
        return cleaned

    def ensure_outlook_running(self) -> None:
        self._run_script("outlook_ensure_running.applescript")

    def preflight_permission_check(self) -> PreflightReport:
        self.ensure_outlook_running()
        try:
            folders = self.list_folders()
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(
                "Outlook preflight failed: AppleScript automation access is denied "
                "or Outlook folder access is unavailable. Grant automation permissions "
                "for this terminal/Python process in System Settings > Privacy & Security > Automation, then retry. "
                f"Original error: {detail}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Outlook preflight failed while validating folder access: {exc}"
            ) from exc

        report = PreflightReport(
            automation_access="ok",
            inbox_access="ok",
            folder_enumeration="ok",
            folder_create="unknown",
            move_support="unknown",
            warnings=[],
            status="ok",
        )
        if not folders:
            report.warnings.append("No Outlook folders were returned during preflight.")

        # Re-check to ensure listing remains stable after warm-up.
        self.list_folders()
        self.preflight_report = report
        return report

    def list_inbox_messages(self, limit: int = 50, max_body_preview_chars: int = 500, **_: object) -> list[OutlookMessage]:
        output = self._run_script("outlook_list_messages.applescript", str(limit), str(max_body_preview_chars))
        raw = safe_json_loads(
            output or "[]",
            context="applescript.list_inbox_messages",
            default=[],
            debug_json=self.debug_json,
        )
        return [OutlookMessage(**msg) for msg in raw if isinstance(msg, dict)]

    def list_folders(self) -> set[str]:
        output = self._run_script("outlook_list_folders.applescript")
        parsed = safe_json_loads(output or "[]", context="applescript.list_folders", default=[], debug_json=self.debug_json)
        return set(parsed if isinstance(parsed, list) else [])

    def create_folder(self, folder_name: str) -> None:
        self._run_script("outlook_create_folder.applescript", folder_name)

    def move_message(self, message_id: str, target_folder: str, apply_enabled: bool) -> None:
        if not apply_enabled:
            raise OutlookSafetyError("Live moves are disabled by configuration.")
        self._run_script("outlook_move_message.applescript", message_id, target_folder)

    def try_apply_followup_flag(self, message_id: str, apply_enabled: bool) -> bool:
        if not apply_enabled:
            return False
        try:
            out = self._run_script("outlook_set_followup_flag.applescript", message_id)
            return out.strip().lower() == "ok"
        except Exception as exc:
            print(f"WARNING: follow-up flagging unsupported or failed: {exc}")
            return False


    def try_mark_tentative(self, message_id: str) -> bool:
        try:
            out = self._run_script("outlook_set_invite_tentative.applescript", message_id)
            return out.strip().lower() == "ok"
        except Exception as exc:
            print(f"WARNING: tentative invite response not supported or failed: {exc}")
            return False

    def send_message(self, *_: str) -> None:
        raise OutlookSafetyError("Sending is prohibited by policy")

    def delete_message(self, *_: str) -> None:
        raise OutlookSafetyError("Deletion is prohibited by policy")
