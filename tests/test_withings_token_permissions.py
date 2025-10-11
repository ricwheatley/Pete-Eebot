import os

import pytest
from unittest.mock import Mock

from pete_e.domain.token_storage import TokenStorage
from pete_e.infrastructure import withings_oauth_helper as oauth_helper
from pete_e.infrastructure.withings_client import WithingsClient


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions only")
def test_save_tokens_sets_owner_only_permissions(tmp_path, monkeypatch):
    token_storage = Mock(spec=TokenStorage)
    token_storage.read_tokens.return_value = None

    client = WithingsClient(token_storage=token_storage)
    client._save_tokens({"access_token": "abc", "refresh_token": "def", "expires_in": 3600})

    token_storage.save_tokens.assert_called_once()
    saved_tokens = token_storage.save_tokens.call_args[0][0]
    assert saved_tokens["access_token"] == "abc"
    assert saved_tokens["refresh_token"] == "def"
    assert "expires_at" in saved_tokens


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

    monkeypatch.setattr(oauth_helper.requests, "post", lambda *_, **__: DummyResponse())

    tokens = oauth_helper.exchange_code_for_tokens("code")

    assert tokens["access_token"] == "abc"
    assert tokens["refresh_token"] == "def"
    mode = token_path.stat().st_mode & 0o777
    assert mode == 0o600
