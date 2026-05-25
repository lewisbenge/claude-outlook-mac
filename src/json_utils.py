from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def sanitize_control_chars(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            code = ord(ch)
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif code < 0x20:
                out.append(f"\\u{code:04x}")
            else:
                out.append(ch)
            continue
        out.append(ch)
        if ch == '"':
            in_string = True
    return "".join(out)


def truncate_payload(payload: Any, limit: int = 500) -> str:
    text = payload if isinstance(payload, str) else repr(payload)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text) - limit} chars>"


def safe_json_loads(raw: str | bytes, *, context: str, default: Any, debug_json: bool = False) -> Any:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    if debug_json:
        print(f"DEBUG_JSON[{context}] raw={truncate_payload(text, 1200)}")
    try:
        return json.loads(text)
    except Exception:
        sanitized = sanitize_control_chars(text)
        if debug_json:
            print(f"DEBUG_JSON[{context}] sanitized={truncate_payload(sanitized, 1200)}")
        try:
            return json.loads(sanitized)
        except Exception as exc:
            print(f"WARNING JSON parse failure in {context}: {exc}; payload={truncate_payload(text)}")
            return default


def safe_json_dump_text(data: Any, *, context: str, default: str = "[]") -> str:
    try:
        return json.dumps(data, indent=2)
    except Exception as exc:
        print(f"WARNING JSON serialization failure in {context}: {exc}")
        return default


def safe_write_json(path: Path, data: Any, *, context: str, default: str = "[]") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(safe_json_dump_text(data, context=context, default=default), encoding="utf-8")
