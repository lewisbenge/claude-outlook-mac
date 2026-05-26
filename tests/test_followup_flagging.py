from src import main as app_main
from src.models import EmailOperationalContext


class _FakeClassifier:
    last_raw_response_preview = "{}"

    def preflight_check(self) -> None:
        pass

    def classify(self, _email_input):
        return (
            EmailOperationalContext(
                operational_class="UNKNOWN",
                waiting_on_me=True,
                follow_up_required=True,
                action_required=True,
                confidence=0.95,
                reason="task",
            ),
            False,
        )


class _Msg:
    message_id = "m1"
    subject = "s"
    sender = "a@b.com"
    recipients = ""
    cc = ""
    body_preview = "please do this"


class _FakeClient:
    def __init__(self, *_args, **_kwargs) -> None:
        self.flag_calls = 0
        self.move_calls = 0

    def preflight_permission_check(self) -> None:
        pass

    def list_inbox_messages(self, **_kwargs):
        return [_Msg()]

    def move_message(self, *_args, **_kwargs):
        self.move_calls += 1

    def try_apply_followup_flag(self, *_args, **_kwargs):
        self.flag_calls += 1
        return True


def test_dry_run_reports_would_flag_but_does_not_apply(monkeypatch):
    fake_client = _FakeClient()
    captured = {}
    monkeypatch.setattr(app_main, "OpenWebUIClassifier", _FakeClassifier)
    monkeypatch.setattr(app_main, "OutlookClient", lambda *_a, **_k: fake_client)
    monkeypatch.setattr(app_main, "write_action_reports", lambda rows: captured.setdefault("rows", rows))
    monkeypatch.setattr("sys.argv", ["prog", "--dry-run"])

    assert app_main.main() == 0
    row = captured["rows"][0]
    assert row["would_flag_followup"] is True
    assert row["followup_flag_applied"] is False
    assert fake_client.flag_calls == 0


def test_apply_mode_flags_only_when_configured(monkeypatch):
    fake_client = _FakeClient()
    captured = {}
    monkeypatch.setenv("FOLLOWUP_FLAG_MODE", "apply")
    monkeypatch.setattr(app_main, "OpenWebUIClassifier", _FakeClassifier)
    monkeypatch.setattr(app_main, "OutlookClient", lambda *_a, **_k: fake_client)
    monkeypatch.setattr(app_main, "write_action_reports", lambda rows: captured.setdefault("rows", rows))
    monkeypatch.setattr("sys.argv", ["prog", "--apply", "--confirm-apply", "MOVE_EMAILS"])

    assert app_main.main() == 0
    row = captured["rows"][0]
    assert row["would_flag_followup"] is True
    assert row["followup_flag_applied"] is True
    assert fake_client.flag_calls == 1
