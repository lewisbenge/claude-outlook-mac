from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from src.json_utils import safe_json_loads, safe_write_json


class ProcessedCache:
    def __init__(self, path: Path, debug_json: bool = False) -> None:
        self.path = path
        self.entries: dict[str, dict] = {}
        self.debug_json = debug_json
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = self.path.read_text(encoding="utf-8", errors="replace")
        data = safe_json_loads(raw, context=f"cache.load:{self.path}", default={}, debug_json=self.debug_json)
        if not isinstance(data, dict):
            return
        if isinstance(data.get("processed_entries"), dict):
            self.entries = data.get("processed_entries", {})
            return
        # Back-compat with legacy cache format.
        for message_id in data.get("processed_ids", []):
            self.entries[message_id] = {
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "processing_mode": "unknown",
                "result_hash": "",
            }

    def save(self) -> None:
        payload = {
            "processed_entries": dict(sorted(self.entries.items())),
        }
        safe_write_json(self.path, payload, context=f"cache.save:{self.path}", default='{"processed_entries": {}}')

    def add(self, message_id: str, *, processing_mode: str, result_hash: str) -> None:
        self.entries[message_id] = {
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "processing_mode": processing_mode,
            "result_hash": result_hash,
        }

    def contains(self, message_id: str, *, ttl_hours: float | None = None) -> bool:
        entry = self.entries.get(message_id)
        if not entry:
            return False
        if ttl_hours is None:
            return True
        processed_at = entry.get("processed_at", "")
        try:
            processed_ts = datetime.fromisoformat(processed_at.replace("Z", "+00:00"))
        except Exception:
            return False
        return datetime.now(timezone.utc) - processed_ts <= timedelta(hours=ttl_hours)

    def result_hash(self, message_id: str) -> str:
        return str(self.entries.get(message_id, {}).get("result_hash", ""))

    def __len__(self) -> int:
        return len(self.entries)

    def reset(self) -> None:
        self.entries.clear()
        if self.path.exists():
            self.path.unlink()


def compute_result_hash(*, classifier_logic_version: str, schema_version: str, prompt_version: str) -> str:
    raw = f"{classifier_logic_version}|{schema_version}|{prompt_version}"
    return sha256(raw.encode("utf-8")).hexdigest()
