import os

import pytest

from pete_e.infrastructure import withings_oauth_helper as oauth_helper
from pete_e.infrastructure.withings_client import WithingsClient


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions only")
def test_save_tokens_sets_owner_only_permissions(tmp_path, monkeypatch):
    token_path = tmp_path / ".withings_tokens.json"
    monkeypatch.setattr(WithingsClient, "TOKEN_FILE", token_path)

    client = WithingsClient()
    client._save_tokens({"access_token": "abc", "refresh_token": "def"})

    mode = token_path.stat().st_mode & 0o777
    assert mode == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions only")
def test_oauth_helper_sets_owner_only_permissions(tmp_path, monkeypatch):
    token_path = tmp_path / ".withings_tokens.json"
    monkeypatch.setattr(oauth_helper, "TOKEN_FILE", token_path)

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"status": 0, "body": {"access_token": "abc", "refresh_token": "def"}}

    monkeypatch.setattr(oauth_helper.requests_mock, "post", lambda *_, **__: DummyResponse())

    tokens = oauth_helper.exchange_code_for_tokens("code")

    assert tokens["access_token"] == "abc"
    assert tokens["refresh_token"] == "def"
    mode = token_path.stat().st_mode & 0o777
    assert mode == 0o600
