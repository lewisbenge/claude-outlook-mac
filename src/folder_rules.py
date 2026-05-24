from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FolderRuleConfig:
    delete_folder_name: str = "Delete"
    max_folder_name_length: int = 64


def sanitize_folder_name(raw_name: str, max_length: int = 64) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _\-]", "", raw_name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return "Needs Review"
    return cleaned[:max_length]


def choose_target_folder(category: str, suggested_folder: str | None, config: FolderRuleConfig) -> str:
    if category == "MOVE_TO_DELETE_FOLDER":
        return config.delete_folder_name
    if category == "MOVE_TO_PROJECT_FOLDER":
        return sanitize_folder_name(suggested_folder or "Needs Review", config.max_folder_name_length)
    return "Inbox"
