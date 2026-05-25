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

    def lookup(self, sender: str, subject: str):
        domain = sender.split("@")[-1].lower() if "@" in sender else ""
        subject_key = subject[:80].lower()
        keys = [f"sender:{sender.lower()}", f"domain:{domain}", f"subject:{subject_key}"]
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
        rows = [
            (f"sender:{sender.lower()}", sender.lower(), domain, subject_key, result.category, result.target_folder, result.confidence),
            (f"domain:{domain}", sender.lower(), domain, subject_key, result.category, result.target_folder, result.confidence),
            (f"subject:{subject_key}", sender.lower(), domain, subject_key, result.category, result.target_folder, result.confidence),
        ]
        with self._lock:
            with self._connect() as con:
                con.executemany(
                    """
                    INSERT INTO classification_cache(key,sender,domain,subject_key,category,target_folder,confidence)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET
                      sender=excluded.sender,domain=excluded.domain,subject_key=excluded.subject_key,
                      category=excluded.category,target_folder=excluded.target_folder,confidence=excluded.confidence,
                      updated_at=CURRENT_TIMESTAMP
                    """,
                    rows,
                )


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
