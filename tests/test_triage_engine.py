from src.triage_engine import ClassificationCache, Metrics, classify_batch, heuristic_classify
from src.claude_cli_classifier import Classification


def test_heuristic_low_value():
    out = heuristic_classify({"subject": "Weekly Newsletter", "sender": "noreply@x.com", "body_preview": ""}, "tentative")
    assert out is not None
    assert out.classification.category == "MOVE_TO_DELETE_FOLDER"


def test_invite_detection():
    out = heuristic_classify({"subject": "Team meeting invitation", "sender": "a@x.com", "body_preview": ""}, "tentative")
    assert out is not None
    assert out.classification.category == "CALENDAR_INVITE"


def test_sqlite_cache_roundtrip(tmp_path):
    c = ClassificationCache(tmp_path / "c.sqlite")
    r = Classification("MOVE_TO_DELETE_FOLDER", "AI Sorted/Delete", 0.95, "x", False)
    c.store("noreply@example.com", "Build failed", r)
    got = c.lookup("noreply@example.com", "Build failed")
    assert got is not None
    assert got.category == "MOVE_TO_DELETE_FOLDER"


def test_heuristic_returns_none_when_no_match():
    out = heuristic_classify({"subject": "Project update", "sender": "person@example.com", "body_preview": "status attached"}, "tentative")
    assert out is None


def test_classify_batch_worker_exception_handling():
    class C:
        def classify(self, meta):
            if meta["subject"] == "boom":
                raise RuntimeError("boom")
            return Classification("KEEP_IN_INBOX", "Inbox", 0.99, "ok", False)

    metrics = Metrics()
    out = classify_batch(C(), [{"subject": "ok"}, {"subject": "boom"}], workers=2, batch_size=2, metrics=metrics)
    assert len(out) == 2
    assert out[0].category == "KEEP_IN_INBOX"
    assert out[1].category == "FAILED"
    assert metrics.c["classifier_failed"] == 1


def test_classify_batch_preserves_order_merge():
    class C:
        def classify(self, meta):
            return Classification("KEEP_IN_INBOX", "Inbox", 0.9, meta["subject"], False)

    metrics = Metrics()
    metas = [{"subject": "first"}, {"subject": "second"}, {"subject": "third"}]
    out = classify_batch(C(), metas, workers=3, batch_size=2, metrics=metrics)
    assert [x.reason for x in out] == ["first", "second", "third"]
