from src.models import EmailOperationalContext


def _base_payload() -> dict:
    return {
        "operational_class": "ADMIN",
        "urgency": "LOW",
        "reason": "test",
        "topics": [],
    }


def test_confidence_high_string_normalized():
    payload = _base_payload() | {"confidence": "high"}
    ctx = EmailOperationalContext.from_dict(payload)
    assert ctx.confidence == 0.9


def test_confidence_medium_string_normalized():
    payload = _base_payload() | {"confidence": "medium"}
    ctx = EmailOperationalContext.from_dict(payload)
    assert ctx.confidence == 0.6


def test_confidence_low_string_normalized():
    payload = _base_payload() | {"confidence": "low"}
    ctx = EmailOperationalContext.from_dict(payload)
    assert ctx.confidence == 0.3


def test_confidence_numeric_string_normalized():
    payload = _base_payload() | {"confidence": "0.75"}
    ctx = EmailOperationalContext.from_dict(payload)
    assert ctx.confidence == 0.75


def test_confidence_missing_defaults_safely():
    ctx = EmailOperationalContext.from_dict(_base_payload())
    assert ctx.confidence == 0.5


def test_confidence_invalid_defaults_safely():
    payload = _base_payload() | {"confidence": "definitely"}
    ctx = EmailOperationalContext.from_dict(payload)
    assert ctx.confidence == 0.5
