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
