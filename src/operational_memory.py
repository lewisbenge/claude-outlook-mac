from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.models import EmailOperationalContext
from src.routing import ORG_NORMALIZATION, normalize_name


TOPIC_HINTS = {"taiwan", "mnd", "aspi", "lattice", "melco", "lnic"}


@dataclass
class AffinityResult:
    normalized_org: str | None = None
    normalized_project: str | None = None
    boosted_confidence: float = 0.0
    sender_affinity_hit: bool = False
    thread_affinity_hit: bool = False
    normalization_hit: bool = False
    confidence_boost_hit: bool = False
    explain: list[str] | None = None


class OperationalMemory:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sender_affinity (
                    sender_domain TEXT,
                    normalized_org TEXT,
                    normalized_project TEXT,
                    routed_target TEXT,
                    avg_confidence REAL DEFAULT 0.0,
                    frequency_count INTEGER DEFAULT 0,
                    last_confidence REAL DEFAULT 0.0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(sender_domain, normalized_org, normalized_project, routed_target)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_affinity (
                    thread_key TEXT PRIMARY KEY,
                    normalized_topic TEXT,
                    routed_target TEXT,
                    dominant_project_customer TEXT,
                    avg_confidence REAL DEFAULT 0.0,
                    frequency_count INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS project_affinity (
                    affinity_key TEXT PRIMARY KEY,
                    domain_cluster TEXT,
                    participant_cluster TEXT,
                    topic_cluster TEXT,
                    dominant_target TEXT,
                    avg_confidence REAL DEFAULT 0.0,
                    frequency_count INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS routing_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT,
                    sender TEXT,
                    sender_domain TEXT,
                    thread_key TEXT,
                    subject TEXT,
                    participants TEXT,
                    topic_cluster TEXT,
                    normalized_org TEXT,
                    normalized_project TEXT,
                    category TEXT,
                    target_folder TEXT,
                    confidence REAL,
                    source TEXT,
                    rerouted_by_user INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @staticmethod
    def make_thread_key(subject: str) -> str:
        normalized = re.sub(r"^(re|fw|fwd)\s*:\s*", "", (subject or "").strip(), flags=re.I)
        normalized = re.sub(r"\s+", " ", normalized).lower()
        return normalized[:160]

    @staticmethod
    def _domain(sender: str) -> str:
        return sender.split("@")[-1].lower() if "@" in sender else ""

    @staticmethod
    def _extract_topic_cluster(subject: str, body_preview: str = "") -> str:
        combined = f"{subject} {body_preview}".lower()
        found = sorted({t for t in TOPIC_HINTS if t in combined})
        return "|".join(found)

    def score(self, *, sender: str, subject: str, body_preview: str, participants: str, ctx: EmailOperationalContext) -> AffinityResult:
        sender_domain = self._domain(sender)
        thread_key = self.make_thread_key(subject)
        topic_cluster = self._extract_topic_cluster(subject, body_preview)
        normalized_org = normalize_name(ctx.customer_or_org)
        normalized_project = normalize_name(ctx.project)
        explain: list[str] = []
        boost = 0.0
        sender_hit = False
        thread_hit = False
        normalization_hit = bool(normalized_org != ctx.customer_or_org or normalized_project != ctx.project)

        with self._connect() as con:
            row = con.execute(
                """SELECT normalized_org, normalized_project, routed_target, avg_confidence, frequency_count
                   FROM sender_affinity
                   WHERE sender_domain=?
                   ORDER BY frequency_count DESC, avg_confidence DESC LIMIT 1""",
                (sender_domain,),
            ).fetchone()
            if row:
                sender_hit = True
                explain.append(f"sender_domain={sender_domain} affinity freq={row[4]}")
                boost += min(0.18, 0.03 * float(row[4]))
                if not normalized_org and row[0]:
                    normalized_org = row[0]
                if not normalized_project and row[1]:
                    normalized_project = row[1]

            row = con.execute(
                "SELECT dominant_project_customer, avg_confidence, frequency_count FROM thread_affinity WHERE thread_key=?",
                (thread_key,),
            ).fetchone()
            if row:
                thread_hit = True
                explain.append(f"thread={thread_key} freq={row[2]}")
                boost += min(0.22, 0.04 * float(row[2]))
                dom = row[0] or ""
                if not normalized_project and dom.startswith("project:"):
                    normalized_project = dom.split(":", 1)[1]
                if not normalized_org and dom.startswith("customer:"):
                    normalized_org = dom.split(":", 1)[1]

            affinity_key = f"{participants.lower()}|{sender_domain}|{topic_cluster}"
            row = con.execute("SELECT frequency_count, avg_confidence, dominant_target FROM project_affinity WHERE affinity_key=?", (affinity_key,)).fetchone()
            if row:
                explain.append(f"participant/topic cluster freq={row[0]}")
                boost += min(0.2, 0.03 * float(row[0]))

        if topic_cluster:
            explain.append(f"topic_cluster={topic_cluster}")
            boost += 0.06
        boosted = max(0.0, min(1.0, float(ctx.confidence) + boost))
        return AffinityResult(
            normalized_org=normalized_org,
            normalized_project=normalized_project,
            boosted_confidence=boosted,
            sender_affinity_hit=sender_hit,
            thread_affinity_hit=thread_hit,
            normalization_hit=normalization_hit,
            confidence_boost_hit=boost > 0.0,
            explain=explain,
        )

    def store_outcome(self, *, message_id: str, sender: str, subject: str, body_preview: str, participants: str, ctx: EmailOperationalContext, target_folder: str, source: str, rerouted_by_user: bool = False) -> None:
        sender_domain = self._domain(sender)
        thread_key = self.make_thread_key(subject)
        normalized_org = normalize_name(ctx.customer_or_org)
        normalized_project = normalize_name(ctx.project)
        topic_cluster = self._extract_topic_cluster(subject, body_preview)
        dominant = f"project:{normalized_project}" if normalized_project else (f"customer:{normalized_org}" if normalized_org else "")
        with self._connect() as con:
            con.execute(
                """INSERT INTO routing_history(
                    message_id,sender,sender_domain,thread_key,subject,participants,topic_cluster,normalized_org,normalized_project,category,target_folder,confidence,source,rerouted_by_user
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (message_id, sender, sender_domain, thread_key, subject, participants, topic_cluster, normalized_org, normalized_project, ctx.operational_class, target_folder, float(ctx.confidence), source, int(rerouted_by_user)),
            )
            con.execute(
                """INSERT INTO sender_affinity(sender_domain, normalized_org, normalized_project, routed_target, avg_confidence, frequency_count, last_confidence)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(sender_domain, normalized_org, normalized_project, routed_target)
                   DO UPDATE SET frequency_count=sender_affinity.frequency_count+1,
                                 avg_confidence=((sender_affinity.avg_confidence*sender_affinity.frequency_count)+excluded.last_confidence)/(sender_affinity.frequency_count+1),
                                 last_confidence=excluded.last_confidence,
                                 updated_at=CURRENT_TIMESTAMP""",
                (sender_domain, normalized_org, normalized_project, target_folder, float(ctx.confidence), 1, float(ctx.confidence)),
            )
            con.execute(
                """INSERT INTO thread_affinity(thread_key, normalized_topic, routed_target, dominant_project_customer, avg_confidence, frequency_count)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(thread_key)
                   DO UPDATE SET frequency_count=thread_affinity.frequency_count+1,
                                 routed_target=excluded.routed_target,
                                 dominant_project_customer=excluded.dominant_project_customer,
                                 avg_confidence=((thread_affinity.avg_confidence*thread_affinity.frequency_count)+excluded.avg_confidence)/(thread_affinity.frequency_count+1),
                                 updated_at=CURRENT_TIMESTAMP""",
                (thread_key, topic_cluster, target_folder, dominant, float(ctx.confidence), 1),
            )
            affinity_key = f"{participants.lower()}|{sender_domain}|{topic_cluster}"
            con.execute(
                """INSERT INTO project_affinity(affinity_key,domain_cluster,participant_cluster,topic_cluster,dominant_target,avg_confidence,frequency_count)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(affinity_key)
                   DO UPDATE SET frequency_count=project_affinity.frequency_count+1,
                                 dominant_target=excluded.dominant_target,
                                 avg_confidence=((project_affinity.avg_confidence*project_affinity.frequency_count)+excluded.avg_confidence)/(project_affinity.frequency_count+1),
                                 updated_at=CURRENT_TIMESTAMP""",
                (affinity_key, sender_domain, participants.lower(), topic_cluster, target_folder, float(ctx.confidence), 1),
            )
