import subprocess
from pathlib import Path

import pytest

from src.outlook_client import OutlookClient


def test_preflight_calls_ensure_and_folder_listing(monkeypatch):
    client = OutlookClient(Path("scripts"))
    calls = []

    def fake_run(name, *args):
        calls.append((name, args))
        if name == "outlook_list_folders.applescript":
            return "[]"
        return "OK"

    monkeypatch.setattr(client, "_run_script", fake_run)

    client.preflight_permission_check()

    assert calls[0][0] == "outlook_ensure_running.applescript"
    assert calls[1][0] == "outlook_list_folders.applescript"
    assert calls[2][0] == "outlook_list_folders.applescript"


def test_preflight_wraps_applescript_permission_errors(monkeypatch):
    client = OutlookClient(Path("scripts"))

    monkeypatch.setattr(client, "ensure_outlook_running", lambda: None)

    def boom(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            1,
            ["osascript"],
            output="",
            stderr="Not authorized to send Apple events to Microsoft Outlook.",
        )

    monkeypatch.setattr(client, "_run_script", boom)

    with pytest.raises(RuntimeError, match="AppleScript automation access is denied"):
        client.preflight_permission_check()
