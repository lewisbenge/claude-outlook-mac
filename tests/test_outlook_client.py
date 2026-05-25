import subprocess
from pathlib import Path

import pytest

from src.outlook_client import OutlookClient


def test_preflight_checks_automation_then_folder_listing(monkeypatch):
    client = OutlookClient(Path("scripts"))
    calls: list[str] = []

    monkeypatch.setattr(client, "ensure_outlook_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(client, "_run_script_inline", lambda _script: calls.append("inline") or "Microsoft Outlook")
    monkeypatch.setattr(client, "list_folders", lambda: calls.append("folders") or {"Inbox"})

    client.preflight_permission_check()

    assert calls == ["ensure", "inline", "folders"]


def test_preflight_wraps_automation_check_errors(monkeypatch):
    client = OutlookClient(Path("scripts"))

    monkeypatch.setattr(client, "ensure_outlook_running", lambda: None)
    monkeypatch.setattr(client, "list_folders", lambda: {"Inbox"})
    def boom(_script):
        raise subprocess.CalledProcessError(
            1,
            ["osascript"],
            output="",
            stderr="Not authorized to send Apple events to Microsoft Outlook.",
        )

    monkeypatch.setattr(client, "_run_script_inline", boom)

    with pytest.raises(RuntimeError, match="AppleScript automation check failed"):
        client.preflight_permission_check()


def test_preflight_falls_back_to_inbox_when_folder_listing_fails(monkeypatch):
    client = OutlookClient(Path("scripts"))
    monkeypatch.setattr(client, "ensure_outlook_running", lambda: None)
    monkeypatch.setattr(client, "_run_script_inline", lambda _script: "Microsoft Outlook")

    def folders_fail():
        raise subprocess.CalledProcessError(1, ["osascript"], output="", stderr="Can't get every folder of missing value")

    monkeypatch.setattr(client, "list_folders", folders_fail)
    monkeypatch.setattr(client, "list_inbox_messages", lambda **_kwargs: [])

    client.preflight_permission_check()
