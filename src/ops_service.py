from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.cache import ProcessedCache
from src.claude_cli_classifier import ClaudeCliClassifier
from src.folder_rules import FolderRuleConfig, choose_target_folder
from src.outlook_client import OutlookClient
from src.triage_engine import ClassificationCache, Metrics, OperationalMetadataStore, classify_batch, enrich_deterministic_meta, heuristic_classify


@dataclass
class Task:
    id: str
    name: str
    status: str
    created_at: float
    updated_at: float
    payload: dict[str, Any]
    result: dict[str, Any] | None = None


class ToolRegistry:
    def __init__(self, runtime: "OpsRuntime") -> None:
        self.runtime = runtime
        self.tools = {
            "inbox_triage": self.runtime.tool_inbox_triage,
            "classify_email": self.runtime.tool_classify_email,
            "move_email": self.runtime.tool_move_email,
            "create_folder": self.runtime.tool_create_folder,
            "tentative_calendar_response": self.runtime.tool_tentative_calendar_response,
            "generate_digest": self.runtime.tool_generate_digest,
        }


class OperationalMemory:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init(self) -> None:
        with self._connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS thread_memory (
                thread_key TEXT PRIMARY KEY,
                project TEXT,
                organization TEXT,
                stakeholders_json TEXT,
                action_required INTEGER,
                priority TEXT,
                thread_summary TEXT,
                recent_decisions_json TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")

    def upsert_thread_memory(self, thread_key: str, payload: dict[str, Any]) -> None:
        with self._connect() as con:
            con.execute(
                """INSERT INTO thread_memory(thread_key,project,organization,stakeholders_json,action_required,priority,thread_summary,recent_decisions_json)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(thread_key) DO UPDATE SET
                  project=excluded.project,organization=excluded.organization,stakeholders_json=excluded.stakeholders_json,
                  action_required=excluded.action_required,priority=excluded.priority,thread_summary=excluded.thread_summary,
                  recent_decisions_json=excluded.recent_decisions_json,updated_at=CURRENT_TIMESTAMP""",
                (
                    thread_key,
                    payload.get("project"),
                    payload.get("organization"),
                    json.dumps(payload.get("stakeholders", [])),
                    payload.get("action_required"),
                    payload.get("priority"),
                    payload.get("thread_summary"),
                    json.dumps(payload.get("recent_decisions", [])),
                ),
            )

    def search(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT thread_key,project,organization,priority,thread_summary,updated_at FROM thread_memory WHERE thread_key LIKE ? OR project LIKE ? OR organization LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            ).fetchall()
        return [{"thread_key": r[0], "project": r[1], "organization": r[2], "priority": r[3], "summary": r[4], "updated_at": r[5]} for r in rows]


class OpsRuntime:
    def __init__(self) -> None:
        self.client = OutlookClient(Path("scripts"))
        self.classifier = ClaudeCliClassifier()
        self.cache = ProcessedCache(Path(".cache/processed_messages.json"))
        self.class_cache = ClassificationCache(Path(".cache/classification_cache.sqlite"))
        self.metadata = OperationalMetadataStore(Path(".cache/classification_cache.sqlite"))
        self.memory = OperationalMemory(Path(".cache/classification_cache.sqlite"))
        self.events: "queue.Queue[dict[str, Any]]" = queue.Queue()

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.put({"kind": kind, "ts": time.time(), **payload})

    def tool_classify_email(self, meta: dict[str, Any]) -> dict[str, Any]:
        data = enrich_deterministic_meta(meta)
        h = heuristic_classify(data, "tentative")
        if h:
            return asdict(h.classification)
        cached = self.class_cache.lookup(data.get("sender", ""), data.get("subject", ""))
        if cached:
            return asdict(cached)
        return asdict(self.classifier.classify(data))

    def tool_inbox_triage(self, payload: dict[str, Any]) -> dict[str, Any]:
        limit = int(payload.get("limit", 25))
        apply = bool(payload.get("apply", False))
        msgs = self.client.list_inbox_messages(limit=limit)
        metrics = Metrics()
        to_classify, pending = [], []
        decisions = []
        self.emit("task_log", {"message": f"triage started ({len(msgs)} messages)"})
        for m in msgs:
            meta = enrich_deterministic_meta({"subject": m.subject, "sender": m.sender, "recipients": m.recipients, "cc": m.cc, "received_at": m.received_at, "folder": m.folder, "body_preview": m.body_preview[:500]})
            h = heuristic_classify(meta, "tentative")
            if h:
                result = h.classification
            else:
                to_classify.append(meta)
                pending.append((m, meta))
                continue
            target = choose_target_folder(result.category, result.target_folder, FolderRuleConfig("AI Sorted", "Delete"))
            decisions.append({"message_id": m.message_id, "subject": m.subject, "category": result.category, "target": target, "confidence": result.confidence})
            self.memory.upsert_thread_memory(meta["thread_key"], {"project": result.project, "organization": result.organization, "stakeholders": result.stakeholders or [], "action_required": result.action_required, "priority": result.priority, "thread_summary": result.short_summary, "recent_decisions": [result.reason]})
            if apply and target != "Inbox":
                self.client.move_message(m.message_id, target, apply_enabled=True)
        classified = classify_batch(self.classifier, to_classify, workers=4, batch_size=4, metrics=metrics)
        for (m, meta), result in zip(pending, classified):
            target = choose_target_folder(result.category, result.target_folder, FolderRuleConfig("AI Sorted", "Delete"))
            decisions.append({"message_id": m.message_id, "subject": m.subject, "category": result.category, "target": target, "confidence": result.confidence})
            self.memory.upsert_thread_memory(meta["thread_key"], {"project": result.project, "organization": result.organization, "stakeholders": result.stakeholders or [], "action_required": result.action_required, "priority": result.priority, "thread_summary": result.short_summary, "recent_decisions": [result.reason]})
            if apply and target != "Inbox":
                self.client.move_message(m.message_id, target, apply_enabled=True)
        self.emit("task_log", {"message": "triage finished", "metrics": metrics.as_dict()})
        return {"decisions": decisions, "metrics": metrics.as_dict()}

    def tool_move_email(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.client.move_message(payload["message_id"], payload["target_folder"], apply_enabled=bool(payload.get("apply_enabled", False)))
        return {"ok": True}

    def tool_create_folder(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.client.create_folder(payload["folder"])
        return {"ok": True}

    def tool_tentative_calendar_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.client.try_mark_tentative(payload["message_id"])
        return {"ok": True}

    def tool_generate_digest(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"digest": "Digest generation scaffold ready.", "window": payload.get("window", "daily")}
