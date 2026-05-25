import subprocess

import pytest

from src.claude_cli_classifier import ClaudeCliClassifier


def test_preflight_missing_cli(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda *_: None)
    c = ClaudeCliClassifier(command='claude')
    with pytest.raises(RuntimeError, match='not found'):
        c.preflight_check()


def test_classify_parses_json(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=['claude'], returncode=0, stdout='{"category":"KEEP_IN_INBOX","target_folder":"Inbox","confidence":0.9,"reason":"ok","needs_user_attention":false}', stderr='')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    c = ClaudeCliClassifier()
    res = c.classify({'subject': 'x'})
    assert res.category == 'KEEP_IN_INBOX'


def test_timeout(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd='claude', timeout=1)

    monkeypatch.setattr(subprocess, 'run', fake_run)
    c = ClaudeCliClassifier(timeout_seconds=1)
    res = c.classify({'subject': 'x'})
    assert res.category == 'NEEDS_REVIEW'


def test_auth_error(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=['claude'], returncode=1, stdout='', stderr='Auth expired, please login')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    c = ClaudeCliClassifier()
    res = c.classify({'subject': 'x'})
    assert res.category == 'NEEDS_REVIEW'
