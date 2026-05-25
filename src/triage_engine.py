from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.claude_cli_classifier import Classification


LOW_VALUE_PATTERNS = [
    re.compile(r"newsletter|unsubscribe|digest", re.I),
    re.compile(r"noreply|do-not-reply|no-reply", re.I),
    re.compile(r"sale|promo|discount|offer", re.I),
    re.compile(r"sales\s+outreach|quick\s+question", re.I),
    re.compile(r"salesforce|sfdc", re.I),
    re.compile(r"alert|notification|automated", re.I),
    re.compile(r"github|pull request|issue", re.I),
    re.compile(r"build failed|ci|cd|pipeline", re.I),
]
INVITE_PATTERNS = [
    re.compile(r"meeting|invite|invitation|calendar", re.I),
    re.compile(r"teams meeting|zoom meeting|google meet", re.I),
]


@dataclass
class TriageOutcome:
    classification: Classification
    source: str


class ClassificationCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS classification_cache (
                  key TEXT PRIMARY KEY,
                  thread_key TEXT,
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

    @staticmethod
    def make_thread_key(subject: str) -> str:
        normalized = re.sub(r"^(re|fw|fwd)\s*:\s*", "", (subject or "").strip(), flags=re.I)
        normalized = re.sub(r"\s+", " ", normalized).lower()
        return normalized[:120]

    def lookup(self, sender: str, subject: str):
        domain = sender.split("@")[-1].lower() if "@" in sender else ""
        subject_key = subject[:80].lower()
        thread_key = self.make_thread_key(subject)
        keys = [f"thread:{thread_key}", f"sender:{sender.lower()}", f"domain:{domain}", f"subject:{subject_key}"]
        with self._connect() as con:
            for key in keys:
                row = con.execute(
                    "SELECT category,target_folder,confidence FROM classification_cache WHERE key=?",
                    (key,),
                ).fetchone()
                if row:
                    return Classification(category=row[0], target_folder=row[1], confidence=float(row[2]), reason="cache hit", needs_user_attention=False)
        return None

    def store(self, sender: str, subject: str, result: Classification):
        domain = sender.split("@")[-1].lower() if "@" in sender else ""
        subject_key = subject[:80].lower()
        thread_key = self.make_thread_key(subject)
        rows = [
            (f"thread:{thread_key}", thread_key, sender.lower(), domain, subject_key, result.category, result.target_folder, result.confidence),
            (f"sender:{sender.lower()}", thread_key, sender.lower(), domain, subject_key, result.category, result.target_folder, result.confidence),
            (f"domain:{domain}", thread_key, sender.lower(), domain, subject_key, result.category, result.target_folder, result.confidence),
            (f"subject:{subject_key}", thread_key, sender.lower(), domain, subject_key, result.category, result.target_folder, result.confidence),
        ]
        with self._lock:
            with self._connect() as con:
                con.executemany(
                    """
                    INSERT INTO classification_cache(key,thread_key,sender,domain,subject_key,category,target_folder,confidence)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET
                      thread_key=excluded.thread_key,sender=excluded.sender,domain=excluded.domain,subject_key=excluded.subject_key,
                      category=excluded.category,target_folder=excluded.target_folder,confidence=excluded.confidence,
                      updated_at=CURRENT_TIMESTAMP
                    """,
                    rows,
                )


class OperationalMetadataStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS stakeholders (id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT)")
            con.execute(
                """CREATE TABLE IF NOT EXISTS email_metadata (
                message_id TEXT PRIMARY KEY,
                thread_key TEXT,
                sender TEXT,
                sender_domain TEXT,
                recurring_thread INTEGER DEFAULT 0,
                calendar_invite INTEGER DEFAULT 0,
                source_system TEXT,
                project_id INTEGER,
                organization TEXT,
                action_required INTEGER,
                priority TEXT,
                topics_json TEXT,
                meeting_related INTEGER,
                contains_decision INTEGER,
                contains_tasking INTEGER,
                short_summary TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id)
                )"""
            )
            con.execute("CREATE TABLE IF NOT EXISTS email_stakeholders (message_id TEXT, stakeholder_id INTEGER, PRIMARY KEY(message_id, stakeholder_id))")

    def _upsert_project(self, con, name: str | None):
        if not name:
            return None
        con.execute("INSERT OR IGNORE INTO projects(name) VALUES(?)", (name.strip(),))
        row = con.execute("SELECT id FROM projects WHERE name=?", (name.strip(),)).fetchone()
        return row[0] if row else None

    def _upsert_stakeholder(self, con, s: str):
        val = (s or "").strip()
        if not val:
            return None
        email = val if "@" in val else None
        name = None if email else val
        con.execute("INSERT OR IGNORE INTO stakeholders(email,name) VALUES(?,?)", (email, name))
        row = con.execute("SELECT id FROM stakeholders WHERE email IS ? AND name IS ?", (email, name)).fetchone()
        return row[0] if row else None

    def store(self, message_id: str, metadata: dict, cls: Classification):
        with self._connect() as con:
            project_id = self._upsert_project(con, getattr(cls, "project", None))
            con.execute(
                """INSERT OR REPLACE INTO email_metadata(
                    message_id,thread_key,sender,sender_domain,recurring_thread,calendar_invite,source_system,project_id,organization,
                    action_required,priority,topics_json,meeting_related,contains_decision,contains_tasking,short_summary
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    message_id,
                    metadata.get("thread_key"),
                    metadata.get("sender"),
                    metadata.get("sender_domain"),
                    int(bool(metadata.get("recurring_thread"))),
                    int(bool(metadata.get("calendar_invite"))),
                    metadata.get("source_system"),
                    project_id,
                    getattr(cls, "organization", None),
                    None if getattr(cls, "action_required", None) is None else int(bool(getattr(cls, "action_required", None))),
                    getattr(cls, "priority", None),
                    str(getattr(cls, "topics", []) or []),
                    None if getattr(cls, "meeting_related", None) is None else int(bool(getattr(cls, "meeting_related", None))),
                    None if getattr(cls, "contains_decision", None) is None else int(bool(getattr(cls, "contains_decision", None))),
                    None if getattr(cls, "contains_tasking", None) is None else int(bool(getattr(cls, "contains_tasking", None))),
                    getattr(cls, "short_summary", None),
                ),
            )
            for s in (getattr(cls, "stakeholders", []) or []):
                sid = self._upsert_stakeholder(con, s)
                if sid:
                    con.execute("INSERT OR IGNORE INTO email_stakeholders(message_id, stakeholder_id) VALUES(?,?)", (message_id, sid))


def enrich_deterministic_meta(meta: dict) -> dict:
    sender = meta.get("sender") or ""
    subject = meta.get("subject") or ""
    body_preview = meta.get("body_preview") or ""
    domain = sender.split("@")[-1].lower() if "@" in sender else ""
    combined = f"{subject} {body_preview}".lower()
    source_system = ""
    if any(token in combined for token in ("salesforce", "sfdc")):
        source_system = "salesforce"
    elif "jira" in combined:
        source_system = "jira"
    elif "github" in combined or "pull request" in combined:
        source_system = "github"
    return {
        **meta,
        "sender_domain": domain,
        "thread_key": ClassificationCache.make_thread_key(subject),
        "recurring_thread": bool(re.search(r"daily|weekly|monthly|digest|summary", combined)),
        "calendar_invite": bool(any(p.search(combined) for p in INVITE_PATTERNS)),
        "source_system": source_system,
    }


class Metrics:
    def __init__(self):
        self.c = Counter()
        self.latencies: list[float] = []

    def record_call(self, latency: float):
        self.c["total_claude_calls"] += 1
        self.latencies.append(latency)

    def as_dict(self):
        avg = sum(self.latencies) / len(self.latencies) if self.latencies else 0.0
        out = dict(self.c)
        out["average_latency"] = round(avg, 3)
        return out


def heuristic_classify(message: dict, invite_mode: str) -> TriageOutcome | None:
    subject = (message.get("subject") or "")
    sender = (message.get("sender") or "")
    body_preview = (message.get("body_preview") or "")
    combined = f"{subject} {sender} {body_preview}"

    if any(p.search(combined) for p in INVITE_PATTERNS):
        return TriageOutcome(Classification("CALENDAR_INVITE", "Inbox", 0.99, f"Invite detected; mode={invite_mode}", False), "invite")

    if any(p.search(combined) for p in LOW_VALUE_PATTERNS):
        return TriageOutcome(Classification("MOVE_TO_DELETE_FOLDER", "AI Sorted/Delete", 0.98, "Heuristic low-value email", False), "heuristic")
    return None


def classify_batch(classifier, metas: Iterable[dict], workers: int, batch_size: int, metrics: Metrics):
    metas = list(metas)
    results = [None] * len(metas)

    def run_one(idx_meta):
        idx, meta = idx_meta
        t0 = time.perf_counter()
        try:
            r = classifier.classify(meta)
            metrics.record_call(time.perf_counter() - t0)
            metrics.c["classifier_completed"] += 1
            return idx, r
        except Exception as exc:
            metrics.c["classifier_failed"] += 1
            return idx, Classification("FAILED", "Inbox", 0.0, f"classifier error: {exc}", True)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for idx, result in ex.map(run_one, list(enumerate(metas)), chunksize=max(1, batch_size)):
            results[idx] = result
    return results
