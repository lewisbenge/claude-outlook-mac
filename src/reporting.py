from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class DecisionLog:
    message_id: str
    subject: str
    sender: str
    recipients: str
    cc: str
    received_at: str
    source_folder: str
    category: str
    confidence: float
    target_folder: str
    reason: str
    needs_user_attention: bool
    action: str


def write_json_report(decisions: Iterable[DecisionLog], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps([asdict(d) for d in decisions], indent=2), encoding="utf-8")


def write_csv_report(decisions: Iterable[DecisionLog], output_path: Path) -> None:
    rows = [asdict(d) for d in decisions]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output_path.write_text("", encoding="utf-8")
        return
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
