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


def test_classify_parses_begin_end_json(monkeypatch):
    payload = 'BEGIN_JSON\n{"category":"KEEP_IN_INBOX","target_folder":"Inbox","confidence":0.9,"reason":"ok","needs_user_attention":false}\nEND_JSON'
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs: subprocess.CompletedProcess(args=['claude'], returncode=0, stdout=payload, stderr=''))
    c = ClaudeCliClassifier()
    res = c.classify({'subject': 'x'})
    assert res.category == 'KEEP_IN_INBOX'
    assert res.raw_response_preview


def test_classify_markdown_fenced_response(monkeypatch):
    payload = '```json\n{"category":"MOVE_TO_DELETE_FOLDER","target_folder":"AI Sorted/Delete","confidence":0.8,"reason":"promo","needs_user_attention":false}\n```'
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs: subprocess.CompletedProcess(args=['claude'], returncode=0, stdout=payload, stderr=''))
    c = ClaudeCliClassifier()
    res = c.classify({'subject': 'x'})
    assert res.category == 'MOVE_TO_DELETE_FOLDER'


def test_classify_parses_escaped_newline_wrapped_json(monkeypatch):
    payload = 'BEGIN_JSON\\n{\\n\\"category\\":\\"KEEP_IN_INBOX\\",\\"target_folder\\":\\"Inbox\\",\\"confidence\\":0.95,\\"reason\\":\\"ok\\",\\"needs_user_attention\\":false\\n}\\nEND_JSON'
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs: subprocess.CompletedProcess(args=['claude'], returncode=0, stdout=payload, stderr=''))
    c = ClaudeCliClassifier()
    res = c.classify({'subject': 'x'})
    assert res.category == 'KEEP_IN_INBOX'


def test_classify_parses_escaped_quote_wrapped_json(monkeypatch):
    payload = 'BEGIN_JSON\\n{\\"category\\":\\"KEEP_IN_INBOX\\",\\"target_folder\\":\\"Inbox\\",\\"confidence\\":0.9,\\"reason\\":\\"quote: \\\\\\"ok\\\\\\"\\" ,\\"needs_user_attention\\":false}\\nEND_JSON'
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs: subprocess.CompletedProcess(args=['claude'], returncode=0, stdout=payload, stderr=''))
    c = ClaudeCliClassifier()
    res = c.classify({'subject': 'x'})
    assert res.category == 'KEEP_IN_INBOX'


def test_classify_prose_response_fallback(monkeypatch):
    payload = "This should probably be NEEDS_REVIEW due to ambiguity."
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs: subprocess.CompletedProcess(args=['claude'], returncode=0, stdout=payload, stderr=''))
    c = ClaudeCliClassifier()
    res = c.classify({'subject': 'x'})
    assert res.category == 'NEEDS_REVIEW'
    assert res.raw_response_preview.startswith("This should")


def test_classify_malformed_json_preserves_raw_preview(monkeypatch):
    payload = '{"category":"KEEP_IN_INBOX","target_folder":"Inbox"'
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs: subprocess.CompletedProcess(args=['claude'], returncode=0, stdout=payload, stderr=''))
    c = ClaudeCliClassifier()
    res = c.classify({'subject': 'x'})
    assert res.category == 'NEEDS_REVIEW'
    assert res.target_folder == "AI Sorted/Needs Review"
    assert res.parse_error
    assert res.raw_response_preview.startswith('{"category"')


def test_prose_plus_json_parses(monkeypatch):
    payload = "email classification follows {\"category\":\"NEEDS_REVIEW\",\"operational_class\":\"UNKNOWN\",\"action\":\"MOVE\",\"target_folder\":\"AI Sorted/Needs Review\",\"confidence\":0.51,\"needs_user_attention\":false,\"reason\":\"uncertain\",\"project\":null,\"customer_or_org\":null,\"routing_source\":\"model\"}"
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess(args=['claude'], returncode=0, stdout=payload, stderr=''))
    c = ClaudeCliClassifier()
    res = c.classify({'subject': 'x'})
    assert res.category == "NEEDS_REVIEW"
    assert res.operational_class == "UNKNOWN"
