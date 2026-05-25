from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


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
    def __init__(self, scripts_dir: Path) -> None:
        self.scripts_dir = scripts_dir
        self.preflight_report: PreflightReport | None = None

    def _run_script(self, script_name: str, *args: str) -> str:
        script_path = self.scripts_dir / script_name
        result = subprocess.run(
            ["osascript", str(script_path), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def ensure_outlook_running(self) -> None:
        self._run_script("outlook_ensure_running.applescript")

    def preflight_permission_check(self) -> PreflightReport:
        self.ensure_outlook_running()
        warnings: list[str] = []
        folder_enumeration = "ok"
        folder_create = "unknown"
        try:
            self._run_script_inline('tell application "Microsoft Outlook" to get name')
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(
                "Outlook preflight failed: AppleScript automation check failed. "
                "Grant automation permissions for this terminal/Python process in "
                "System Settings > Privacy & Security > Automation, then retry. "
                f"Original error: {detail}"
            ) from exc

        try:
            self.list_inbox_messages(limit=1, max_body_preview_chars=1)
        except Exception as exc:
            raise RuntimeError(f"Outlook preflight failed: inbox access check failed. Original error: {exc}") from exc

        try:
            self.list_folders()
        except subprocess.CalledProcessError as folder_exc:
            folder_detail = (folder_exc.stderr or folder_exc.stdout or str(folder_exc)).strip()
            folder_enumeration = "folder_enumeration_unavailable"
            warnings.append(f"Folder enumeration unavailable: {folder_detail}")
            try:
                self.create_folder("AI Sorted")
                folder_create = "ok"
            except Exception as create_exc:
                folder_create = "unavailable"
                warnings.append(f"Direct folder creation check failed: {create_exc}")
        except Exception as exc:
            folder_enumeration = "folder_enumeration_unavailable"
            warnings.append(f"Folder enumeration unavailable: {exc}")
            try:
                self.create_folder("AI Sorted")
                folder_create = "ok"
            except Exception as create_exc:
                folder_create = "unavailable"
                warnings.append(f"Direct folder creation check failed: {create_exc}")

        if folder_enumeration == "ok":
            folder_create = "ok"

        report = PreflightReport(
            automation_access="ok",
            inbox_access="ok",
            folder_enumeration=folder_enumeration,
            folder_create=folder_create,
            move_support="supported_with_safety_gate",
            warnings=warnings,
            status="PASS_WITH_WARNINGS" if warnings else "PASS",
        )
        self.preflight_report = report
        return report

    def _run_script_inline(self, script: str) -> str:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def list_inbox_messages(self, limit: int = 50, max_body_preview_chars: int = 500, **_: object) -> list[OutlookMessage]:
        output = self._run_script("outlook_list_messages.applescript", str(limit), str(max_body_preview_chars))
        raw = json.loads(output or "[]")
        return [OutlookMessage(**msg) for msg in raw]

    def list_folders(self) -> set[str]:
        output = self._run_script("outlook_list_folders.applescript")
        return set(json.loads(output or "[]"))

    def create_folder(self, folder_name: str) -> None:
        self._run_script("outlook_create_folder.applescript", folder_name)

    def move_message(self, message_id: str, target_folder: str, apply_enabled: bool) -> None:
        if not apply_enabled:
            raise OutlookSafetyError("Live moves are disabled by configuration.")
        self._run_script("outlook_move_message.applescript", message_id, target_folder)

    def send_message(self, *_: str) -> None:
        raise OutlookSafetyError("Sending is prohibited by policy")

    def delete_message(self, *_: str) -> None:
        raise OutlookSafetyError("Deletion is prohibited by policy")
