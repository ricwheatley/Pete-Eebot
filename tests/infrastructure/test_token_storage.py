import json
import os

import pytest

from pete_e.infrastructure.token_storage import JsonFileTokenStorage


def test_read_tokens_returns_none_when_missing(tmp_path):
    storage = JsonFileTokenStorage(tmp_path / "tokens.json")

    assert storage.read_tokens() is None


def test_save_and_read_tokens_round_trip(tmp_path):
    path = tmp_path / "nested" / "tokens.json"
    storage = JsonFileTokenStorage(path)

    payload = {"access_token": "abc", "refresh_token": "def"}
    storage.save_tokens(payload)

    with path.open("r", encoding="utf-8") as handle:
        assert json.load(handle) == payload

    assert storage.read_tokens() == payload


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions only")
def test_save_tokens_sets_restrictive_permissions(tmp_path):
    path = tmp_path / "tokens.json"
    storage = JsonFileTokenStorage(path)

    storage.save_tokens({"access_token": "abc"})

    mode = path.stat().st_mode & 0o777
    assert mode == 0o600
