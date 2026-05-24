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
        try:
            result = subprocess.run(["osascript", str(script_path), *args], capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.stderr.strip() or f"Failed script: {script_name}") from exc
        return result.stdout.strip()

    def ensure_outlook_running(self) -> None:
        self._run_script("outlook_ensure_running.applescript")

    def list_inbox_messages(self, limit: int = 50, max_body_preview_chars: int = 500) -> list[OutlookMessage]:
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
