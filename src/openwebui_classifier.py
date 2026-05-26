from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass

from src.models import EmailOperationalContext


@dataclass
class EmailInput:
    subject: str
    sender: str
    recipients: str = ""
    cc: str = ""
    body_preview: str = ""


class OpenWebUIClassifier:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("OPENWEBUI_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("OPENWEBUI_API_KEY", "")
        self.model = model or os.getenv("OPENWEBUI_MODEL", "")
        self.last_raw_response_preview = ""
        self.last_http_status = "unknown"

    @staticmethod
    def _safe_unknown_context(reason: str) -> EmailOperationalContext:
        return EmailOperationalContext.from_dict(
            {
                "operational_class": "UNKNOWN",
                "needs_user_attention": True,
                "follow_up_required": True,
                "action_required": False,
                "clear_action_for_user": False,
                "should_leave_in_inbox": False,
                "suggested_review_folder": "AI Sorted/Needs Review",
                "urgency": "LOW",
                "waiting_on_me": True,
                "waiting_on_external": False,
                "confidence": 0.0,
                "reason": reason,
                "topics": ["needs_review"],
            }
        )

    @staticmethod
    def _extract_first_json_object(content: str) -> str | None:
        start = content.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(content)):
            ch = content[idx]
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return content[start : idx + 1]
        return None

    def _parse_context_with_fallback(self, content: str) -> tuple[EmailOperationalContext | None, str | None]:
        try:
            return EmailOperationalContext.from_dict(json.loads(content)), None
        except Exception as direct_error:
            extracted = self._extract_first_json_object(content)
            if extracted:
                try:
                    return EmailOperationalContext.from_dict(json.loads(extracted)), None
                except Exception as extracted_error:
                    return None, f"direct parse failed: {direct_error}; extracted parse failed: {extracted_error}"
            return None, f"direct parse failed: {direct_error}; no balanced JSON object found"

    def _response_diag(self, out: dict, content: str | None) -> None:
        response_keys = list(out.keys()) if isinstance(out, dict) else []
        choices = out.get("choices") if isinstance(out, dict) else None
        choices_len = len(choices) if isinstance(choices, list) else 0
        finish_reason = None
        if choices_len > 0 and isinstance(choices[0], dict):
            finish_reason = choices[0].get("finish_reason")
        preview = "" if content is None else content[:200].replace("\n", "\\n")
        print(
            f"[openwebui] http_status={self.last_http_status} response_keys={response_keys} choices_len={choices_len} "
            f"finish_reason={finish_reason} content_preview={preview!r}"
        )

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(req, timeout=45) as resp:
            self.last_http_status = str(getattr(resp, "status", "unknown"))
            return json.loads(resp.read().decode("utf-8"))

    def preflight_check(self) -> None:
        if not self.base_url or not self.model:
            raise RuntimeError("OPENWEBUI_BASE_URL and OPENWEBUI_MODEL must be configured")
        data = self._request("GET", "/api/models")
        ids = {m.get("id") for m in data.get("data", [])}
        if self.model not in ids:
            raise RuntimeError("Configured model not found")

    def classify(self, email: EmailInput) -> tuple[EmailOperationalContext, bool]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "You are helping clear the Inbox. Do not keep emails in Inbox unless there is a clear action assigned to Lewis. Project/customer relevance is not an action. FYSA, updates, briefings, notifications, and general awareness emails should be moved to folders. Uncertain emails go to Needs Review, not Inbox. Return only a JSON object containing allowed keys: operational_class, customer_or_org, project, needs_user_attention, action_required, follow_up_required, action_summary, clear_action_for_user, inbox_retention_reason, suggested_review_folder, should_leave_in_inbox, urgency, waiting_on_me, waiting_on_external, deadline_detected, confidence, reason, topics. should_leave_in_inbox must only be true when clear_action_for_user is true. Never include extra keys. Never include subject, sender, recipients, cc, body, or any raw email metadata. confidence must be a number from 0.0 to 1.0, not text. No prose or markdown. Examples: 'Can you send the deck by Friday?' => clear_action_for_user=true, should_leave_in_inbox=true. 'FYSA, updated briefing attached' => clear_action_for_user=false. 'Flight booking reminder' => TRAVEL. 'Weekly newsletter' => NEWSLETTER or SALES_SPAM. 'Customer meeting notes, no request' => clear_action_for_user=false. 'I need your approval' => clear_action_for_user=true. 'General project update' => clear_action_for_user=false."},
                {"role": "user", "content": f"subject:{email.subject}\nfrom:{email.sender}\nbody:{email.body_preview}"},
            ],
        }
        for attempt in range(2):
            out = self._request("POST", "/api/chat/completions", payload)
            choices = out.get("choices") if isinstance(out, dict) else None
            first_choice = choices[0] if isinstance(choices, list) and choices else {}
            message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
            content = message.get("content") if isinstance(message, dict) else None
            self._response_diag(out if isinstance(out, dict) else {}, content)
            if content is None:
                if attempt == 0:
                    continue
                return self._safe_unknown_context("OpenWebUI response missing message/content after retry"), True

            content = content.strip()
            self.last_raw_response_preview = content[:1000]
            if not content:
                if attempt == 0:
                    continue
                return self._safe_unknown_context("OpenWebUI returned empty content after retry"), True

            parsed, parse_error = self._parse_context_with_fallback(content)
            if parsed is not None:
                return parsed, attempt == 1
            if attempt == 0:
                continue
            return self._safe_unknown_context(f"OpenWebUI parse failure: {parse_error}"), True
        return self._safe_unknown_context("OpenWebUI classification failed unexpectedly"), True
