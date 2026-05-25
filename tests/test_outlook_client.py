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


def test_run_script_uses_utf8_and_sanitizes_surrogates(monkeypatch):
    client = OutlookClient(Path("scripts"))

    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args=["osascript"], returncode=0, stdout="Bad\ud83dText", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = client._run_script("outlook_list_folders.applescript")
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert "\ud83d" not in out


def test_list_inbox_messages_unicode_roundtrip(monkeypatch):
    client = OutlookClient(Path("scripts"))
    payload = '[{"message_id":"1","subject":"こんにちは","sender":"汤𠮷","recipients":"","cc":"","received_at":"now","folder":"Inbox","body_preview":"Привет"}]'
    monkeypatch.setattr(client, "_run_script", lambda *_args: payload)
    msgs = client.list_inbox_messages()
    assert msgs[0].subject == "こんにちは"
    assert msgs[0].sender == "汤𠮷"
