from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FolderRuleConfig:
    root_folder_name: str = "AI Sorted"
    delete_folder_leaf: str = "Delete"
    max_folder_name_length: int = 64


def sanitize_folder_name(raw_name: str, max_length: int = 64) -> str:
    cleaned = raw_name.replace("/", "-").replace("\\", "-").replace('"', "")
    cleaned = re.sub(r"[^A-Za-z0-9 _\-]", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return "Needs Review"
    return cleaned[:max_length]


def _ai_path(cfg: FolderRuleConfig, leaf: str) -> str:
    return f"{cfg.root_folder_name}/{sanitize_folder_name(leaf, cfg.max_folder_name_length)}"


def choose_target_folder(category: str, suggested_folder: str | None, config: FolderRuleConfig) -> str:
    if category == "MOVE_TO_DELETE_FOLDER":
        return _ai_path(config, config.delete_folder_leaf)
    if category == "MOVE_TO_PROJECT_FOLDER":
        return _ai_path(config, suggested_folder or "Needs Review")
    return "Inbox"
