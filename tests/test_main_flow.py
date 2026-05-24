from types import SimpleNamespace

import src.main as mainmod


def test_parser_defaults():
    args = mainmod.build_parser().parse_args([])
    assert args.limit == 25
    assert args.max_body_preview_chars == 500


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

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.8")
    monkeypatch.setattr(mainmod, "OutlookClient", lambda *_: C())
    monkeypatch.setattr(mainmod, "BedrockClassifier", lambda *_: B())
    monkeypatch.setattr(mainmod, "load_dotenv", lambda: None)
    monkeypatch.setattr(mainmod, "run_preflight", lambda *_: None)
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


def test_str_to_bool_variants():
    assert mainmod.str_to_bool("true") is True
    assert mainmod.str_to_bool("false") is False
    assert mainmod.str_to_bool("1") is True
    assert mainmod.str_to_bool("0") is False
    assert mainmod.str_to_bool(True) is True
    assert mainmod.str_to_bool(False) is False
    assert mainmod.str_to_bool(None) is False


def test_str_too_bool_backcompat_alias():
    assert mainmod.str_too_bool("true") is True
    assert mainmod.str_too_bool("0") is False
