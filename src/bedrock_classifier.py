from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from src.json_utils import safe_json_loads, sanitize_control_chars, truncate_payload


@dataclass
class Classification:
    category: str
    target_folder: str
    confidence: float
    reason: str
    needs_user_attention: bool


class BedrockClassifier:
    def __init__(self, region: str, model_id: str, debug_json: bool = False) -> None:
        try:
            import boto3
        except ModuleNotFoundError as exc:
            raise RuntimeError("boto3 is required for Bedrock classification") from exc
        profile_name = os.getenv("AWS_PROFILE") or None
        self.session = boto3.Session(profile_name=profile_name, region_name=region)
        self._validate_session_credentials()
        self.client = self.session.client("bedrock-runtime")
        self.model_id = model_id
        self.profile_name = profile_name
        self.region = self.session.region_name or region
        self.debug_json = debug_json

    def _validate_session_credentials(self) -> None:
        creds = self.session.get_credentials()
        if creds is None:
            profile_name = os.getenv("AWS_PROFILE") or "default credential chain"
            raise RuntimeError(
                f"AWS credentials are not configured or could not be resolved for '{profile_name}'. "
                "Run `aws sts get-caller-identity` to verify your environment/profile."
            )

    def preflight_check(self) -> None:
        self._validate_session_credentials()
        active_profile = self.session.profile_name or os.getenv("AWS_PROFILE") or "(default)"
        active_region = self.session.region_name or self.region or "(unset)"
        print(
            "AWS preflight: "
            f"profile={active_profile}, "
            f"region={active_region}, "
            "credentials_resolved=true"
        )

    def classify(self, message: dict) -> Classification:
        prompt = (
            "Classify the email metadata into one category: KEEP_IN_INBOX, "
            "MOVE_TO_PROJECT_FOLDER, MOVE_TO_DELETE_FOLDER, NEEDS_REVIEW. "
            "Return ONLY valid JSON with keys: category,target_folder,confidence,reason,needs_user_attention. "
            "Do not include markdown. Do not include explanation text. "
            f"Email: {json.dumps(message)}"
        )
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        })
        resp = self.client.invoke_model(modelId=self.model_id, body=body)
        payload = safe_json_loads(
            resp["body"].read(),
            context="bedrock.response",
            default={},
            debug_json=getattr(self, "debug_json", False),
        )
        text = payload.get("content", [{}])[0].get("text", "") if isinstance(payload, dict) else ""
        print(f"Bedrock raw response (truncated): {repr(text[:500])}")
        try:
            extracted = self._extract_first_json_object(text)
            sanitized = sanitize_control_chars(extracted)
            data = safe_json_loads(sanitized, context="bedrock.extracted_json", default={}, debug_json=getattr(self, "debug_json", False))
            return Classification(**data)
        except Exception as exc:
            print(f"Bedrock parsing error: {exc}; payload={truncate_payload(text)}")
            return Classification(
                category="NEEDS_REVIEW",
                target_folder="Inbox",
                confidence=0.0,
                reason="Model response parsing failed",
                needs_user_attention=True,
            )

    @staticmethod
    def _extract_first_json_object(text: str) -> str:
        fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if fence_match:
            text = fence_match.group(1)
        start = text.find("{")
        if start == -1:
            raise ValueError("No JSON object start found")
        depth = 0
        in_string = False
        escaped = False
        for i, ch in enumerate(text[start:], start=start):
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        raise ValueError("No complete JSON object found")
