from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from src.json_utils import safe_write_json


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
    safe_write_json(output_path, [asdict(d) for d in decisions], context=f"report.write:{output_path}")


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
