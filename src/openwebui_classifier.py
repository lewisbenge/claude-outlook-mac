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

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(req, timeout=45) as resp:
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
                {"role": "system", "content": "You are a structured extraction API. Return only a JSON object containing allowed keys: operational_class, customer_or_org, project, needs_user_attention, action_required, follow_up_required, action_summary, urgency, waiting_on_me, waiting_on_external, deadline_detected, confidence, reason, topics. Never include extra keys. Never include subject, sender, recipients, cc, body, or any raw email metadata. confidence must be a number from 0.0 to 1.0, not text. No prose or markdown."},
                {"role": "user", "content": f"subject:{email.subject}\nfrom:{email.sender}\nbody:{email.body_preview}"},
            ],
        }
        for attempt in range(2):
            out = self._request("POST", "/api/chat/completions", payload)
            content = out["choices"][0]["message"]["content"]
            self.last_raw_response_preview = content[:1000]
            try:
                return EmailOperationalContext.from_dict(json.loads(content)), attempt == 1
            except Exception:
                if attempt == 1:
                    raise
        raise RuntimeError("unreachable")
