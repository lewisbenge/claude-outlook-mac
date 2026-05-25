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
