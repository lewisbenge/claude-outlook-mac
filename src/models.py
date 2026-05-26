from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields

ALLOWED_CLASS = {
    "CUSTOMER","PROJECT","TRAVEL","CALENDAR","ADMIN","FINANCE","NEWSLETTER","AUTOMATION","SALES_SPAM","PERSONAL","UNKNOWN"
}
ALLOWED_URGENCY = {"LOW", "MEDIUM", "HIGH"}
CONFIDENCE_TEXT_MAP = {"high": 0.9, "medium": 0.6, "low": 0.3}


@dataclass
class EmailOperationalContext:
    operational_class: str
    customer_or_org: str | None = None
    project: str | None = None
    needs_user_attention: bool = False
    action_required: bool = False
    follow_up_required: bool = False
    action_summary: str | None = None
    urgency: str = "LOW"
    waiting_on_me: bool = False
    waiting_on_external: bool = False
    deadline_detected: str | None = None
    confidence: float = 0.0
    reason: str = ""
    topics: list[str] = field(default_factory=list)

    @classmethod
    def allowed_fields(cls) -> set[str]:
        return {f.name for f in dataclass_fields(cls)}

    def __post_init__(self) -> None:
        if self.operational_class not in ALLOWED_CLASS:
            raise ValueError("invalid operational_class")
        if self.urgency not in ALLOWED_URGENCY:
            raise ValueError("invalid urgency")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError("confidence out of range")

    @classmethod
    def from_dict(cls, data: dict) -> "EmailOperationalContext":
        if not isinstance(data, dict):
            raise ValueError("schema payload must be an object")
        filtered = {k: v for k, v in data.items() if k in cls.allowed_fields()}
        if "operational_class" in filtered and filtered["operational_class"] not in ALLOWED_CLASS:
            filtered["operational_class"] = "UNKNOWN"
        if "urgency" in filtered and filtered["urgency"] not in ALLOWED_URGENCY:
            filtered["urgency"] = "LOW"
        filtered["confidence"] = cls._normalize_confidence(filtered.get("confidence"))
        return cls(**filtered)

    @staticmethod
    def _normalize_confidence(raw_confidence: object) -> float:
        if raw_confidence is None:
            return 0.5

        if isinstance(raw_confidence, str):
            value = CONFIDENCE_TEXT_MAP.get(raw_confidence.strip().lower())
            if value is None:
                try:
                    value = float(raw_confidence)
                except (TypeError, ValueError):
                    value = 0.5
        else:
            try:
                value = float(raw_confidence)
            except (TypeError, ValueError):
                value = 0.5

        return max(0.0, min(1.0, value))
