import sqlite3

from src.triage_engine import ClassificationCache, Metrics, classify_batch, enrich_deterministic_meta, heuristic_classify
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


def test_customer_email_weak_signal_not_deleted():
    out = heuristic_classify({"subject": "Capability planning notes", "sender": "person@vendor.com", "body_preview": "weekly update"}, "tentative")
    assert out is not None
    assert out.classification.category == "NEEDS_REVIEW"


def test_protected_domain_not_deleted(monkeypatch):
    monkeypatch.setenv("CUSTOMER_DOMAINS", "customer.com")
    out = heuristic_classify({"subject": "Weekly digest", "sender": "noreply@customer.com", "body_preview": ""}, "tentative")
    assert out is not None
    assert out.classification.category == "NEEDS_REVIEW"


def test_noreply_marketing_still_deletes():
    out = heuristic_classify({"subject": "unsubscribe now", "sender": "noreply@news.com", "body_preview": ""}, "tentative")
    assert out is not None
    assert out.classification.category == "MOVE_TO_DELETE_FOLDER"


def test_salesforce_noise_still_deletes():
    out = heuristic_classify({"subject": "Salesforce notification", "sender": "bot@crm.com", "body_preview": "automated alert"}, "tentative")
    assert out is not None
    assert out.classification.category == "MOVE_TO_DELETE_FOLDER"


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


def test_enrich_deterministic_meta_extracts_operational_fields():
    out = enrich_deterministic_meta({"subject": "Re: Weekly Jira digest", "sender": "bot@example.com", "body_preview": "Jira issue changed"})
    assert out["sender_domain"] == "example.com"
    assert out["recurring_thread"] is True
    assert out["source_system"] == "jira"


def test_sqlite_migrates_legacy_schema_without_thread_key(tmp_path):
    db = tmp_path / "legacy.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE classification_cache (
          key TEXT PRIMARY KEY,
          sender TEXT,
          domain TEXT,
          subject_key TEXT,
          category TEXT,
          target_folder TEXT,
          confidence REAL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.close()

    c = ClassificationCache(db)
    info = c.migrate()
    assert info["current_version"] >= 1

    with sqlite3.connect(db) as con2:
        cols = [r[1] for r in con2.execute("PRAGMA table_info(classification_cache)").fetchall()]
    assert "thread_key" in cols


def test_sqlite_migrations_are_idempotent(tmp_path):
    db = tmp_path / "idem.sqlite"
    c = ClassificationCache(db)
    first = c.migrate()
    second = c.migrate()
    assert first["current_version"] >= 1
    assert second["migrations_applied"] == []
