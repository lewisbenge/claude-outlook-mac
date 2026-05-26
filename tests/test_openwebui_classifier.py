from unittest.mock import patch

from src.openwebui_classifier import EmailInput, OpenWebUIClassifier


def test_schema_validation_retry():
    c = OpenWebUIClassifier(base_url="http://x", model="gpt-4o")
    bad = {"choices": [{"message": {"content": "not-json"}}]}
    good = {
        "choices": [
            {
                "message": {
                    "content": '{"operational_class":"TRAVEL","customer_or_org":null,"project":null,"needs_user_attention":false,"action_required":false,"follow_up_required":false,"action_summary":null,"urgency":"LOW","waiting_on_me":false,"waiting_on_external":false,"deadline_detected":null,"confidence":0.91,"reason":"flight reminder","topics":["travel"]}'
                }
            }
        ]
    }

    with patch.object(c, "_request", side_effect=[bad, good]):
        ctx, retried = c.classify(EmailInput(subject="s", sender="a@b.com"))
    assert retried is True
    assert ctx.operational_class == "TRAVEL"


def test_extra_field_subject_ignored():
    c = OpenWebUIClassifier(base_url="http://x", model="gpt-4o")
    out = {
        "choices": [
            {
                "message": {
                    "content": '{"operational_class":"TRAVEL","urgency":"LOW","confidence":0.5,"reason":"x","topics":[],"subject":"bad"}'
                }
            }
        ]
    }
    with patch.object(c, "_request", return_value=out):
        ctx, retried = c.classify(EmailInput(subject="s", sender="a@b.com"))
    assert retried is False
    assert ctx.operational_class == "TRAVEL"


def test_extra_field_sender_ignored():
    c = OpenWebUIClassifier(base_url="http://x", model="gpt-4o")
    out = {
        "choices": [
            {
                "message": {
                    "content": '{"operational_class":"PROJECT","urgency":"MEDIUM","confidence":0.7,"reason":"x","topics":["p"],"sender":"bad@x.com"}'
                }
            }
        ]
    }
    with patch.object(c, "_request", return_value=out):
        ctx, _ = c.classify(EmailInput(subject="s", sender="a@b.com"))
    assert ctx.operational_class == "PROJECT"


def test_invalid_enum_fallbacks_to_safe_values():
    c = OpenWebUIClassifier(base_url="http://x", model="gpt-4o")
    out = {
        "choices": [
            {
                "message": {
                    "content": '{"operational_class":"NOT_REAL","urgency":"URGENT","confidence":0.8,"reason":"x","topics":[]}'
                }
            }
        ]
    }
    with patch.object(c, "_request", return_value=out):
        ctx, _ = c.classify(EmailInput(subject="s", sender="a@b.com"))
    assert ctx.operational_class == "UNKNOWN"
    assert ctx.urgency == "LOW"


def test_missing_optional_fields_ok():
    c = OpenWebUIClassifier(base_url="http://x", model="gpt-4o")
    out = {
        "choices": [
            {
                "message": {
                    "content": '{"operational_class":"ADMIN"}'
                }
            }
        ]
    }
    with patch.object(c, "_request", return_value=out):
        ctx, retried = c.classify(EmailInput(subject="s", sender="a@b.com"))
    assert retried is False
    assert ctx.operational_class == "ADMIN"
    assert ctx.urgency == "LOW"


def test_missing_required_field_retries_once_then_succeeds():
    c = OpenWebUIClassifier(base_url="http://x", model="gpt-4o")
    missing_required = {
        "choices": [
            {
                "message": {
                    "content": '{"urgency":"LOW","confidence":0.5,"reason":"x","topics":[]}'
                }
            }
        ]
    }
    good = {
        "choices": [
            {
                "message": {
                    "content": '{"operational_class":"ADMIN","urgency":"LOW","confidence":0.5,"reason":"x","topics":[]}'
                }
            }
        ]
    }

    with patch.object(c, "_request", side_effect=[missing_required, good]):
        ctx, retried = c.classify(EmailInput(subject="s", sender="a@b.com"))
    assert retried is True
    assert ctx.operational_class == "ADMIN"
