import os

from src import main as app_main


class _FakeClassifier:
    def preflight_check(self) -> None:
        assert os.getenv("OPENWEBUI_BASE_URL") == "http://example.local"
        assert os.getenv("OPENWEBUI_MODEL") == "mock-model"
        assert os.getenv("OPENWEBUI_API_KEY") == "secret-key"


class _FakeClient:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def preflight_permission_check(self) -> None:
        pass

    def debug_test_move(self) -> str:
        return "OK"


def test_env_loaded_before_openwebui_preflight(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENWEBUI_BASE_URL=http://example.local\n"
        "OPENWEBUI_MODEL=mock-model\n"
        "OPENWEBUI_API_KEY=secret-key\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("OPENWEBUI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENWEBUI_MODEL", raising=False)
    monkeypatch.delenv("OPENWEBUI_API_KEY", raising=False)
    monkeypatch.setattr(app_main, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(app_main, "OpenWebUIClassifier", _FakeClassifier)
    monkeypatch.setattr(app_main, "OutlookClient", _FakeClient)
    monkeypatch.setattr("sys.argv", ["prog", "--preflight-only"])

    assert app_main.main() == 0


def test_test_move_mode_runs_without_classifier(monkeypatch, capsys):
    monkeypatch.setattr(app_main, "initialize_environment", lambda *_args, **_kwargs: None)

    class _Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def preflight_permission_check(self) -> None:
            pass

        def debug_test_move(self) -> str:
            return "debug-output"

    class _Classifier:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("classifier should not be initialized for --test-move")

    monkeypatch.setattr(app_main, "OutlookClient", _Client)
    monkeypatch.setattr(app_main, "OpenWebUIClassifier", _Classifier)
    monkeypatch.setattr("sys.argv", ["prog", "--test-move"])

    assert app_main.main() == 0
    assert "debug-output" in capsys.readouterr().out
