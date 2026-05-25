import os
import types

import pytest

from src.bedrock_classifier import BedrockClassifier


class _FakeSession:
    def __init__(self, profile_name=None, region_name=None, creds=object()):
        self.profile_name = profile_name
        self.region_name = region_name
        self._creds = creds

    def get_credentials(self):
        return self._creds

    def client(self, _name):
        return object()



def test_uses_aws_profile_when_present(monkeypatch):
    captured = {}

    def session_factory(profile_name=None, region_name=None):
        captured['profile_name'] = profile_name
        captured['region_name'] = region_name
        return _FakeSession(profile_name=profile_name, region_name=region_name)

    monkeypatch.setitem(__import__('sys').modules, 'boto3', types.SimpleNamespace(Session=session_factory))
    monkeypatch.setenv('AWS_PROFILE', 'dev-profile')

    c = BedrockClassifier('us-east-1', 'model')
    assert captured['profile_name'] == 'dev-profile'
    assert c.profile_name == 'dev-profile'



def test_raises_when_credentials_missing(monkeypatch):
    def session_factory(profile_name=None, region_name=None):
        return _FakeSession(profile_name=profile_name, region_name=region_name, creds=None)

    monkeypatch.setitem(__import__('sys').modules, 'boto3', types.SimpleNamespace(Session=session_factory))
    monkeypatch.delenv('AWS_PROFILE', raising=False)

    with pytest.raises(RuntimeError, match='AWS credentials are not configured'):
        BedrockClassifier('us-east-1', 'model')


class _Body:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


class _FakeClient:
    def __init__(self, model_text):
        self.model_text = model_text

    def invoke_model(self, **_kwargs):
        payload = {"content": [{"text": self.model_text}]}
        return {"body": _Body(__import__('json').dumps(payload))}


def _classifier_for_text(text):
    c = BedrockClassifier.__new__(BedrockClassifier)
    c.client = _FakeClient(text)
    c.model_id = 'model'
    return c


def test_classify_parses_markdown_wrapped_json():
    c = _classifier_for_text("""```json\n{\"category\":\"KEEP_IN_INBOX\",\"target_folder\":\"Inbox\",\"confidence\":0.95,\"reason\":\"ok\",\"needs_user_attention\":false}\n```""")
    res = c.classify({"subject": "test"})
    assert res.category == 'KEEP_IN_INBOX'


def test_classify_parses_prose_before_json_with_raw_newline_and_tab():
    c = _classifier_for_text(
        "Here you go:\n{\"category\":\"NEEDS_REVIEW\",\"target_folder\":\"Inbox\",\"confidence\":0.4,\"reason\":\"line1\nline2\tindent\",\"needs_user_attention\":true}"
    )
    res = c.classify({"subject": "test"})
    assert res.category == 'NEEDS_REVIEW'
    assert "line2\tindent" in res.reason


def test_classify_invalid_json_falls_back_to_needs_review():
    c = _classifier_for_text("not json at all")
    res = c.classify({"subject": "test"})
    assert res.category == 'NEEDS_REVIEW'
    assert res.needs_user_attention is True
