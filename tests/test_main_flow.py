from types import SimpleNamespace

import pytest

import src.main as mainmod


def test_parser_defaults():
    args = mainmod.build_parser().parse_args([])
    assert args.limit == 25
    assert args.max_body_preview_chars == 500
    assert args.claude_timeout_seconds is None


def test_low_confidence_forces_review(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()

    class C:
        def ensure_outlook_running(self):
            pass
        def list_inbox_messages(self, **kwargs):
            return [SimpleNamespace(message_id="1", subject="s", sender="a", recipients="", cc="", received_at="now", folder="Inbox", body_preview="bp")]
        def list_folders(self):
            return set()
        def create_folder(self, *_):
            pass
        def move_message(self, *_ , **__):
            raise AssertionError("should not move")

    class B:
        def classify(self, _):
            return SimpleNamespace(category="MOVE_TO_PROJECT_FOLDER", target_folder="X", confidence=0.1, reason="low", needs_user_attention=True)

    monkeypatch.setenv("CLASSIFIER_BACKEND", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.8")
    monkeypatch.setattr(mainmod, "OutlookClient", lambda *_: C())
    monkeypatch.setattr(mainmod, "BedrockClassifier", lambda *_: B())
    monkeypatch.setattr(mainmod, "load_dotenv", lambda: None)
    monkeypatch.setattr(mainmod, "run_preflight", lambda *_: None)
    monkeypatch.setattr(mainmod.ClassificationCache, "lookup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("sys.argv", ["prog", "--dry-run"])
    assert mainmod.main() == 0


def test_apply_disabled_safety(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()

    moved = {"called": False}

    class C:
        def ensure_outlook_running(self):
            pass
        def list_inbox_messages(self, **kwargs):
            return [SimpleNamespace(message_id="1", subject="s", sender="a", recipients="", cc="", received_at="now", folder="Inbox", body_preview="bp")]
        def list_folders(self):
            return {"AI Sorted"}
        def create_folder(self, *_):
            pass
        def move_message(self, *_ , **__):
            moved["called"] = True
            raise Exception("disabled")

    class B:
        def classify(self, _):
            return SimpleNamespace(category="MOVE_TO_DELETE_FOLDER", target_folder="Delete", confidence=0.99, reason="junk", needs_user_attention=False)

    monkeypatch.setenv("CLASSIFIER_BACKEND", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    monkeypatch.setenv("ALLOW_APPLY", "false")
    monkeypatch.setattr(mainmod, "OutlookClient", lambda *_: C())
    monkeypatch.setattr(mainmod, "BedrockClassifier", lambda *_: B())
    monkeypatch.setattr(mainmod, "load_dotenv", lambda: None)
    monkeypatch.setattr(mainmod, "run_preflight", lambda *_: None)
    monkeypatch.setattr("sys.argv", ["prog", "--apply", "--confirm-apply", "MOVE_EMAILS"])
    assert mainmod.main() == 0
    assert moved["called"] is True


def test_run_preflight_rejects_missing_preflight_report(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    class C:
        preflight_report = None

        def preflight_permission_check(self):
            return None

    class B:
        def preflight_check(self):
            pass

    monkeypatch.setenv("CLASSIFIER_BACKEND", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    with pytest.raises(RuntimeError, match="no preflight report was returned"):
        mainmod.run_preflight(C(), B())


def test_all_direct_to_me_inbox(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()

    class C:
        def ensure_outlook_running(self):
            pass
        def list_inbox_messages(self, **kwargs):
            return [SimpleNamespace(message_id="1", subject="a", sender="x", recipients="me@example.com", cc="", received_at="now", folder="Inbox", body_preview=""),
                    SimpleNamespace(message_id="2", subject="b", sender="y", recipients="me@example.com", cc="", received_at="now", folder="Inbox", body_preview="")]
        def list_folders(self):
            return set()

    class B:
        def classify(self, _):
            raise AssertionError("classifier should not be called")

    monkeypatch.setenv("CLASSIFIER_BACKEND", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    monkeypatch.setenv("USER_EMAIL", "me@example.com")
    monkeypatch.setattr(mainmod, "OutlookClient", lambda *_: C())
    monkeypatch.setattr(mainmod, "BedrockClassifier", lambda *_: B())
    monkeypatch.setattr(mainmod, "load_dotenv", lambda: None)
    monkeypatch.setattr(mainmod, "run_preflight", lambda *_: None)
    monkeypatch.setattr("sys.argv", ["prog", "--dry-run"])
    assert mainmod.main() == 0


def test_claude_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()

    class C:
        def ensure_outlook_running(self):
            pass
        def list_inbox_messages(self, **kwargs):
            return []
        def list_folders(self):
            return set()

    captured = {}

    class FakeClaude:
        def __init__(self, command="claude", timeout_seconds=0, debug_json=False):
            captured["timeout_seconds"] = timeout_seconds
            captured["command"] = command
        def preflight_check(self):
            pass

    monkeypatch.setenv("CLASSIFIER_BACKEND", "claude_cli")
    monkeypatch.setattr(mainmod, "OutlookClient", lambda *_args, **_kwargs: C())
    monkeypatch.setattr(mainmod, "ClaudeCliClassifier", FakeClaude)
    monkeypatch.setattr(mainmod, "run_preflight", lambda *_: None)
    monkeypatch.setattr(mainmod, "load_dotenv", lambda: None)
    monkeypatch.setattr("sys.argv", ["prog", "--dry-run"])
    assert mainmod.main() == 0
    assert captured["timeout_seconds"] == 180


def test_claude_timeout_override(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()

    class C:
        def ensure_outlook_running(self):
            pass
        def list_inbox_messages(self, **kwargs):
            return []
        def list_folders(self):
            return set()

    captured = {}

    class FakeClaude:
        def __init__(self, command="claude", timeout_seconds=0, debug_json=False):
            captured["timeout_seconds"] = timeout_seconds
        def preflight_check(self):
            pass

    monkeypatch.setenv("CLASSIFIER_BACKEND", "claude_cli")
    monkeypatch.setenv("CLAUDE_TIMEOUT_SECONDS", "222")
    monkeypatch.setattr(mainmod, "OutlookClient", lambda *_args, **_kwargs: C())
    monkeypatch.setattr(mainmod, "ClaudeCliClassifier", FakeClaude)
    monkeypatch.setattr(mainmod, "run_preflight", lambda *_: None)
    monkeypatch.setattr(mainmod, "load_dotenv", lambda: None)
    monkeypatch.setattr("sys.argv", ["prog", "--dry-run", "--claude-timeout-seconds", "240"])
    assert mainmod.main() == 0
    assert captured["timeout_seconds"] == 240


def test_dry_run_does_not_suppress_reruns(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()
    calls = {"n": 0}

    class C:
        def ensure_outlook_running(self):
            pass
        def list_inbox_messages(self, **kwargs):
            return [SimpleNamespace(message_id="1", subject="s", sender="a@example.com", recipients="", cc="", received_at="now", folder="Inbox", body_preview="bp")]
        def list_folders(self):
            return set()

    class B:
        def classify(self, _):
            calls["n"] += 1
            return SimpleNamespace(category="KEEP_IN_INBOX", target_folder="Inbox", confidence=0.99, reason="ok", needs_user_attention=False)

    monkeypatch.setenv("CLASSIFIER_BACKEND", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    monkeypatch.setattr(mainmod, "OutlookClient", lambda *_: C())
    monkeypatch.setattr(mainmod, "BedrockClassifier", lambda *_: B())
    monkeypatch.setattr(mainmod, "load_dotenv", lambda: None)
    monkeypatch.setattr(mainmod, "run_preflight", lambda *_: None)
    monkeypatch.setattr(mainmod.ClassificationCache, "lookup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("sys.argv", ["prog", "--dry-run"])
    assert mainmod.main() == 0
    monkeypatch.setattr("sys.argv", ["prog", "--dry-run"])
    assert mainmod.main() == 0
    assert calls["n"] == 2


def test_apply_mode_suppresses_subsequent_run(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()
    calls = {"n": 0}

    class C:
        def ensure_outlook_running(self):
            pass
        def list_inbox_messages(self, **kwargs):
            return [SimpleNamespace(message_id="1", subject="s", sender="a@example.com", recipients="", cc="", received_at="now", folder="Inbox", body_preview="bp")]
        def list_folders(self):
            return {"AI Sorted"}
        def create_folder(self, *_args, **_kwargs):
            return None
        def move_message(self, *_args, **_kwargs):
            return None

    class B:
        def classify(self, _):
            calls["n"] += 1
            return SimpleNamespace(category="MOVE_TO_DELETE_FOLDER", target_folder="AI Sorted/Delete", confidence=0.99, reason="junk", needs_user_attention=False)

    monkeypatch.setenv("CLASSIFIER_BACKEND", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    monkeypatch.setenv("ALLOW_APPLY", "true")
    monkeypatch.setattr(mainmod, "OutlookClient", lambda *_: C())
    monkeypatch.setattr(mainmod, "BedrockClassifier", lambda *_: B())
    monkeypatch.setattr(mainmod, "load_dotenv", lambda: None)
    monkeypatch.setattr(mainmod, "run_preflight", lambda *_: None)
    monkeypatch.setattr("sys.argv", ["prog", "--apply", "--confirm-apply", "MOVE_EMAILS"])
    assert mainmod.main() == 0
    monkeypatch.setattr("sys.argv", ["prog", "--apply", "--confirm-apply", "MOVE_EMAILS"])
    assert mainmod.main() == 0
    assert calls["n"] == 1


def test_ignore_cache_forces_reprocessing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()
    calls = {"n": 0}

    class C:
        def ensure_outlook_running(self):
            pass
        def list_inbox_messages(self, **kwargs):
            return [SimpleNamespace(message_id="1", subject="s", sender="a@example.com", recipients="", cc="", received_at="now", folder="Inbox", body_preview="bp")]
        def list_folders(self):
            return {"AI Sorted"}
        def create_folder(self, *_args, **_kwargs):
            return None
        def move_message(self, *_args, **_kwargs):
            return None

    class B:
        def classify(self, _):
            calls["n"] += 1
            return SimpleNamespace(category="MOVE_TO_DELETE_FOLDER", target_folder="AI Sorted/Delete", confidence=0.99, reason="junk", needs_user_attention=False)

    monkeypatch.setenv("CLASSIFIER_BACKEND", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    monkeypatch.setenv("ALLOW_APPLY", "true")
    monkeypatch.setattr(mainmod, "OutlookClient", lambda *_: C())
    monkeypatch.setattr(mainmod, "BedrockClassifier", lambda *_: B())
    monkeypatch.setattr(mainmod, "load_dotenv", lambda: None)
    monkeypatch.setattr(mainmod, "run_preflight", lambda *_: None)
    monkeypatch.setattr(mainmod.ClassificationCache, "lookup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("sys.argv", ["prog", "--apply", "--confirm-apply", "MOVE_EMAILS"])
    assert mainmod.main() == 0
    monkeypatch.setattr("sys.argv", ["prog", "--apply", "--confirm-apply", "MOVE_EMAILS", "--ignore-cache"])
    assert mainmod.main() == 0
    assert calls["n"] == 2


def test_cache_ttl_expiry(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()
    calls = {"n": 0}

    class C:
        def ensure_outlook_running(self):
            pass
        def list_inbox_messages(self, **kwargs):
            return [SimpleNamespace(message_id="1", subject="s", sender="a@example.com", recipients="", cc="", received_at="now", folder="Inbox", body_preview="bp")]
        def list_folders(self):
            return {"AI Sorted"}
        def create_folder(self, *_args, **_kwargs):
            return None
        def move_message(self, *_args, **_kwargs):
            return None

    class B:
        def classify(self, _):
            calls["n"] += 1
            return SimpleNamespace(category="MOVE_TO_DELETE_FOLDER", target_folder="AI Sorted/Delete", confidence=0.99, reason="junk", needs_user_attention=False)

    monkeypatch.setenv("CLASSIFIER_BACKEND", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    monkeypatch.setenv("ALLOW_APPLY", "true")
    monkeypatch.setattr(mainmod, "OutlookClient", lambda *_: C())
    monkeypatch.setattr(mainmod, "BedrockClassifier", lambda *_: B())
    monkeypatch.setattr(mainmod, "load_dotenv", lambda: None)
    monkeypatch.setattr(mainmod, "run_preflight", lambda *_: None)
    monkeypatch.setattr(mainmod.ClassificationCache, "lookup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("sys.argv", ["prog", "--apply", "--confirm-apply", "MOVE_EMAILS"])
    assert mainmod.main() == 0
    monkeypatch.setattr("sys.argv", ["prog", "--apply", "--confirm-apply", "MOVE_EMAILS", "--cache-ttl-hours", "0"])
    assert mainmod.main() == 0
    assert calls["n"] == 2
