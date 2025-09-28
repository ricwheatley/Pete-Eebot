from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from scripts.check_auth import (
    AuthStatus,
    determine_dropbox_status,
    determine_withings_status,
    load_env_file,
)


def test_withings_status_ok_when_token_file_present(tmp_path):
    token_file = tmp_path / ".withings_tokens.json"
    token_file.write_text(json.dumps({"refresh_token": "abc", "access_token": "def"}))
    updated_at = datetime(2024, 5, 1, 8, 30, tzinfo=timezone.utc)
    os.utime(token_file, (updated_at.timestamp(), updated_at.timestamp()))

    status = determine_withings_status({}, token_file)

    assert isinstance(status, AuthStatus)
    assert status.state == "ok"
    assert "Refresh token stored" in status.message
    assert "2024-05-01 08:30 UTC" in status.message


def test_withings_status_warns_when_only_env_refresh_token(tmp_path):
    token_file = tmp_path / ".withings_tokens.json"

    status = determine_withings_status({"WITHINGS_REFRESH_TOKEN": "abc"}, token_file)

    assert status.state == "warning"
    assert "refresh-withings" in status.message


def test_withings_status_requires_setup_when_app_config_present(tmp_path):
    token_file = tmp_path / ".withings_tokens.json"

    env = {
        "WITHINGS_CLIENT_ID": "abc",
        "WITHINGS_CLIENT_SECRET": "def",
        "WITHINGS_REDIRECT_URI": "https://example.com/redirect",
    }

    status = determine_withings_status(env, token_file)

    assert status.state == "action_required"
    assert "withings-auth" in status.message


def test_withings_status_flags_missing_app_settings(tmp_path):
    token_file = tmp_path / ".withings_tokens.json"

    env = {"WITHINGS_CLIENT_ID": "abc"}

    status = determine_withings_status(env, token_file)

    assert status.state == "action_required"
    assert "WITHINGS_CLIENT_SECRET" in status.message
    assert "WITHINGS_REDIRECT_URI" in status.message


def test_dropbox_status_ok_when_all_present():
    env = {
        "DROPBOX_APP_KEY": "key",
        "DROPBOX_APP_SECRET": "secret",
        "DROPBOX_REFRESH_TOKEN": "token",
    }

    status = determine_dropbox_status(env)

    assert status.state == "ok"
    assert "App key, secret, and refresh token" in status.message


def test_dropbox_status_prompts_for_refresh_token_only():
    env = {"DROPBOX_APP_KEY": "key", "DROPBOX_APP_SECRET": "secret"}

    status = determine_dropbox_status(env)

    assert status.state == "action_required"
    assert "DROPBOX_REFRESH_TOKEN" in status.message


def test_dropbox_status_prompts_for_multiple_missing():
    env = {}

    status = determine_dropbox_status(env)

    assert status.state == "action_required"
    assert "DROPBOX_APP_KEY" in status.message
    assert "DROPBOX_APP_SECRET" in status.message


def test_env_loader_handles_export_and_quotes(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # comment line
        export DROPBOX_APP_KEY="abc123"
        DROPBOX_REFRESH_TOKEN='xyz'
        INVALID_LINE
        
        WITHINGS_CLIENT_ID = something
        """
    )

    result = load_env_file(env_file)

    assert result["DROPBOX_APP_KEY"] == "abc123"
    assert result["DROPBOX_REFRESH_TOKEN"] == "xyz"
    assert result["WITHINGS_CLIENT_ID"] == "something"
    assert "INVALID_LINE" not in result

