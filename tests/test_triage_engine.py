from src.triage_engine import ClassificationCache, heuristic_classify
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
