from __future__ import annotations

from pathlib import Path

from src.json_utils import safe_json_loads, safe_write_json


class ProcessedCache:
    def __init__(self, path: Path, debug_json: bool = False) -> None:
        self.path = path
        self.ids: set[str] = set()
        self.debug_json = debug_json
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = self.path.read_text(encoding="utf-8", errors="replace")
        data = safe_json_loads(raw, context=f"cache.load:{self.path}", default={}, debug_json=self.debug_json)
        self.ids = set(data.get("processed_ids", [])) if isinstance(data, dict) else set()

    def save(self) -> None:
        safe_write_json(self.path, {"processed_ids": sorted(self.ids)}, context=f"cache.save:{self.path}", default='{"processed_ids": []}')

    def add(self, message_id: str) -> None:
        self.ids.add(message_id)

    def contains(self, message_id: str) -> bool:
        return message_id in self.ids

    def reset(self) -> None:
        self.ids.clear()
        if self.path.exists():
            self.path.unlink()
