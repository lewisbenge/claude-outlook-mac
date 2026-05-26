from __future__ import annotations

import re
import sqlite3
import threading
import time
import os
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
OPERATIONAL_ROUTING_RULES = [
    ("TRAVEL", "travel_signal", re.compile(r"flight|itinerary|boarding pass|airline|trip|travel", re.I), "Travel"),
    ("TRAVEL", "lodging_transport", re.compile(r"hotel|reservation|booking confirmation|rental car|car hire", re.I), "Travel"),
    ("MOVE_TO_CALENDAR_FOLDER", "calendar_signal", re.compile(r"calendar invite|invitation|meeting accepted|meeting declined|teams meeting|zoom meeting", re.I), "Calendar"),
    ("FINANCE", "finance_signal", re.compile(r"expense|receipt|invoice|billing|payment due|reimbursement", re.I), "Finance"),
    ("MOVE_TO_DELETE_FOLDER", "newsletter_signal", re.compile(r"newsletter|digest|unsubscribe", re.I), "Delete"),
]
CUSTOMER_SAFETY_PATTERNS = [
    re.compile(r"rico|anduril|capability|sec|official|customer|briefing|proposal|mnd|army", re.I),
]
STRONG_DELETE_RULES = [
    ("noreply_sender", "sender", re.compile(r"noreply|do-not-reply|no-reply", re.I)),
    ("marketing_unsubscribe", "subject_or_body", re.compile(r"unsubscribe|newsletter|digest", re.I)),
    ("known_automation", "subject_or_body", re.compile(r"salesforce|sfdc|automated|alert|notification", re.I)),
    ("sales_outreach", "subject_or_body", re.compile(r"sales\s+outreach|quick\s+question|discount|offer|promo|sale", re.I)),
    ("spam_like", "subject_or_body", re.compile(r"free money|crypto giveaway|urgent winnings", re.I)),
]
INVITE_PATTERNS = [
    re.compile(r"meeting|invite|invitation|calendar", re.I),
    re.compile(r"teams meeting|zoom meeting|google meet", re.I),
]
ACTION_PHRASES = [
    re.compile(r"\bcan you\b", re.I),
    re.compile(r"\bplease provide\b", re.I),
    re.compile(r"\bneed your review\b", re.I),
    re.compile(r"\baction:\b", re.I),
    re.compile(r"\bcould you\b", re.I),
    re.compile(r"\bby (eod|tomorrow|[a-z]+\s+\d{1,2})\b", re.I),
]
INFORMATIONAL_PHRASES = [
    re.compile(r"\bfysa\b", re.I),
    re.compile(r"\bfor your awareness\b", re.I),
    re.compile(r"\bcustomer update\b", re.I),
    re.compile(r"\bweekly update\b", re.I),
    re.compile(r"\bstatus update\b", re.I),
    re.compile(r"\bbriefing attached\b", re.I),
    re.compile(r"\bmeeting notes\b", re.I),
    re.compile(r"\bminutes\b", re.I),
    re.compile(r"\bdistribution list\b", re.I),
]


@dataclass
class TriageOutcome:
    classification: Classification
    source: str
    routing_source: str = ""
    inherited_from_thread: bool = False
    inherited_from_sender: bool = False
    heuristic_match: str = ""


class ClassificationCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _column_exists(con, table_name: str, column_name: str) -> bool:
        rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(r[1] == column_name for r in rows)

    def _ensure_migrations_table(self, con) -> None:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              applied_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _ensure_base_tables(self, con) -> None:
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

    def _apply_migrations(self, con) -> list[int]:
        migrations = [
            (1, "add_classification_cache_thread_key"),
        ]
        applied: list[int] = []
        for version, name in migrations:
            already = con.execute("SELECT 1 FROM schema_migrations WHERE version=?", (version,)).fetchone()
            if already:
                continue
            if version == 1 and not self._column_exists(con, "classification_cache", "thread_key"):
                con.execute("ALTER TABLE classification_cache ADD COLUMN thread_key TEXT")
            con.execute("INSERT OR IGNORE INTO schema_migrations(version,name) VALUES(?,?)", (version, name))
            applied.append(version)
        return applied

    def migrate(self) -> dict:
        with self._connect() as con:
            self._ensure_base_tables(con)
            self._ensure_migrations_table(con)
            applied = self._apply_migrations(con)
            current = con.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
            return {"current_version": int(current), "migrations_applied": applied}

    def _init_db(self):
        self.migrate()

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
            try:
                for key in keys:
                    row = con.execute(
                        "SELECT category,target_folder,confidence,updated_at FROM classification_cache WHERE key=?",
                        (key,),
                    ).fetchone()
                    if row:
                        age_days = con.execute("SELECT CAST((julianday('now') - julianday(?)) AS REAL)", (row[3],)).fetchone()[0] or 0.0
                        decay = max(0.35, 1.0 - min(float(age_days), 60.0) * 0.01)
                        inherited_from_thread = key.startswith("thread:")
                        inherited_from_sender = key.startswith("sender:") or key.startswith("domain:")
                        confidence = float(row[2]) * decay
                        category = row[0]
                        target_folder = row[1]
                        if inherited_from_sender and category == "MOVE_TO_PROJECT_FOLDER":
                            category = "NEEDS_REVIEW"
                            target_folder = "Inbox"
                            confidence *= 0.6
                        return Classification(
                            category=category,
                            target_folder=target_folder,
                            confidence=confidence,
                            reason=f"cache hit; routing_source={key}; inherited_from_thread={inherited_from_thread}; inherited_from_sender={inherited_from_sender}; decay={decay:.2f}",
                            needs_user_attention=False,
                        )
            except sqlite3.OperationalError:
                self.migrate()
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
                try:
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
                except sqlite3.OperationalError:
                    self.migrate()
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
        # Schema bootstrap/migrations are handled by ClassificationCache for this shared DB.
        ClassificationCache(self.db_path).migrate()

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

    def record_timeout(self):
        self.c["claude_timeouts"] += 1

    def as_dict(self):
        avg = sum(self.latencies) / len(self.latencies) if self.latencies else 0.0
        out = dict(self.c)
        out["claude_average_latency"] = round(avg, 3)
        out["average_latency"] = round(avg, 3)
        return out


def heuristic_classify(message: dict, invite_mode: str) -> TriageOutcome | None:
    subject = (message.get("subject") or "")
    sender = (message.get("sender") or "")
    body_preview = (message.get("body_preview") or "")
    combined = f"{subject} {sender} {body_preview}"
    cc = (message.get("cc") or "")
    recipients = (message.get("recipients") or "")
    sender_domain = sender.split("@")[-1].lower() if "@" in sender else ""

    def _csv_set(name: str) -> set[str]:
        return {x.strip().lower() for x in (os.getenv(name, "")).split(",") if x.strip()}

    protected_domains = _csv_set("PROTECTED_DOMAINS") | _csv_set("CUSTOMER_DOMAINS")
    protected_senders = _csv_set("PROTECTED_SENDERS")
    protected_reason = ""
    if sender.lower() in protected_senders:
        protected_reason = "protected_sender"
    elif sender_domain in protected_domains:
        protected_reason = "protected_domain"

    def explain(reason: str, matched_rule: str, matched_pattern: str, matched_field: str, is_protected: str = "") -> str:
        return (
            f"{reason} | matched_rule={matched_rule} | matched_pattern={matched_pattern} "
            f"| matched_field={matched_field} | sender_domain={sender_domain} "
            f"| protected_reason={is_protected or 'none'}"
        )

    for p in CUSTOMER_SAFETY_PATTERNS:
        if p.search(subject):
            return TriageOutcome(
                Classification("NEEDS_REVIEW", "AI Sorted/Needs Review", 0.8, explain("Customer-safety override", "customer_safety_override", p.pattern, "subject", protected_reason), True),
                "heuristic",
                routing_source="customer_guard",
                heuristic_match="customer_safety_override",
            )

    if protected_reason:
        return TriageOutcome(
            Classification("NEEDS_REVIEW", "Inbox", 0.85, explain("Protected sender/domain", "protected_sender_domain", protected_reason, "sender", protected_reason), True),
            "heuristic",
            routing_source="protected_sender_domain",
            inherited_from_sender=True,
            heuristic_match="protected_sender_domain",
        )
    informational_hit = any(p.search(combined) for p in INFORMATIONAL_PHRASES)
    action_hits = [p.pattern for p in ACTION_PHRASES if p.search(combined)]
    cc_only_info = informational_hit and sender and recipients and sender.lower() not in recipients.lower()
    if informational_hit and not action_hits:
        return TriageOutcome(
            Classification("PROJECT", "AI Sorted/Projects/General", 0.76, explain("Informational email without direct ask", "informational_only", "|".join(action_hits) or "none", "subject_or_body", protected_reason), False),
            "heuristic",
            routing_source="informational",
            heuristic_match="cc_informational" if cc_only_info else "informational_only",
        )
    if action_hits:
        return TriageOutcome(
            Classification("NEEDS_REVIEW", "Inbox", 0.88, explain("Action phrase detected", "direct_ask", "|".join(action_hits), "subject_or_body", protected_reason), True),
            "heuristic",
            routing_source="action_detection",
            heuristic_match="direct_ask",
        )
    for klass, rule_name, pat, folder in OPERATIONAL_ROUTING_RULES:
        if pat.search(combined):
            return TriageOutcome(
                Classification(klass, folder, 0.99, explain("Operational deterministic routing", rule_name, pat.pattern, "subject_or_body", protected_reason), False),
                "heuristic",
                routing_source="operational",
                heuristic_match=rule_name,
            )

    for rule_name, field, pat in STRONG_DELETE_RULES:
        haystack = sender if field == "sender" else f"{subject} {body_preview}"
        if pat.search(haystack):
            return TriageOutcome(
                Classification("MOVE_TO_DELETE_FOLDER", "AI Sorted/Delete", 0.98, explain("Heuristic low-value email", rule_name, pat.pattern, field, protected_reason), False),
                "heuristic",
                routing_source="heuristic_delete",
                heuristic_match=rule_name,
            )

    if any(p.search(combined) for p in LOW_VALUE_PATTERNS):
        return TriageOutcome(
            Classification("NEEDS_REVIEW", "AI Sorted/Needs Review", 0.65, explain("Weak low-value signal escalated", "weak_low_value", "LOW_VALUE_PATTERNS", "subject_or_body", protected_reason), True),
            "heuristic",
        )
    return None


def classify_batch(classifier, metas: Iterable[dict], workers: int, batch_size: int, metrics: Metrics):
    metas = list(metas)
    results = [None] * len(metas)

    def run_one(idx_meta):
        idx, meta = idx_meta
        t0 = time.perf_counter()
        try:
            r = classifier.classify(meta)
            latency = getattr(classifier, "last_latency_seconds", None)
            metrics.record_call(latency if latency is not None else (time.perf_counter() - t0))
            if r.category == "NEEDS_REVIEW" and "timeout" in (r.reason or "").lower():
                metrics.record_timeout()
            metrics.c["classifier_completed"] += 1
            return idx, r
        except Exception as exc:
            metrics.c["classifier_failed"] += 1
            return idx, Classification("FAILED", "Inbox", 0.0, f"classifier error: {exc}", True)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for idx, result in ex.map(run_one, list(enumerate(metas)), chunksize=max(1, batch_size)):
            results[idx] = result
    return results
