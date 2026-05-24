from __future__ import annotations

import json
from dataclasses import dataclass



@dataclass
class Classification:
    category: str
    target_folder: str
    confidence: float
    reason: str
    needs_user_attention: bool


class BedrockClassifier:
    def __init__(self, region: str, model_id: str) -> None:
        try:
            import boto3
        except ModuleNotFoundError as exc:
            raise RuntimeError("boto3 is required for Bedrock classification") from exc
        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id

    def classify(self, message: dict) -> Classification:
        prompt = (
            "Classify the email metadata into one category: KEEP_IN_INBOX, "
            "MOVE_TO_PROJECT_FOLDER, MOVE_TO_DELETE_FOLDER, NEEDS_REVIEW. "
            "Return strict JSON only with keys: category,target_folder,confidence,reason,needs_user_attention. "
            f"Email: {json.dumps(message)}"
        )
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        })
        resp = self.client.invoke_model(modelId=self.model_id, body=body)
        payload = json.loads(resp["body"].read())
        text = payload["content"][0]["text"]
        data = json.loads(text)
        return Classification(**data)
