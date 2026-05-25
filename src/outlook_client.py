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


class OutlookClient:
    def __init__(self, scripts_dir: Path) -> None:
        self.scripts_dir = scripts_dir

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

    def preflight_permission_check(self) -> None:
        self.ensure_outlook_running()
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
            self.list_folders()
            return
        except subprocess.CalledProcessError as folder_exc:
            folder_detail = (folder_exc.stderr or folder_exc.stdout or str(folder_exc)).strip()
            try:
                self.list_inbox_messages(limit=1, max_body_preview_chars=1)
                return
            except Exception as inbox_exc:
                raise RuntimeError(
                    "Outlook preflight failed: folder listing failed and inbox fallback also failed. "
                    f"Folder listing error: {folder_detail}. "
                    f"Inbox fallback error: {inbox_exc}"
                ) from folder_exc
        except Exception as exc:
            raise RuntimeError(
                f"Outlook preflight failed while validating folder access: {exc}"
            ) from exc

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
