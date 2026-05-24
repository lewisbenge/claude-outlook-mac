from __future__ import annotations

import json
from pathlib import Path


class ProcessedCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.ids: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.ids = set(data.get("processed_ids", []))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"processed_ids": sorted(self.ids)}, indent=2), encoding="utf-8")

    def add(self, message_id: str) -> None:
        self.ids.add(message_id)

    def contains(self, message_id: str) -> bool:
        return message_id in self.ids

    def reset(self) -> None:
        self.ids.clear()
        if self.path.exists():
            self.path.unlink()
