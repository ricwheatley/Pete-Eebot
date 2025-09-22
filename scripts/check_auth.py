"""Utility for checking Pete Eebot auth prerequisites.

This module inspects the locally stored Withings token file and the
environment-backed Dropbox credentials to confirm that the inputs needed for
scheduled syncs are present. No network calls are performed – the script only
looks at files and configuration values that already exist on disk.

Run via ``python -m scripts.check_auth`` to print a small status report.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


TOKEN_FILE_NAME = ".withings_tokens.json"


@dataclass(frozen=True)
class AuthStatus:
    """Represents the outcome of a credential check."""

    name: str
    state: str
    message: str

    def format_line(self) -> str:
        """Render the status in a CLI-friendly format."""

        labels = {
            "ok": "OK",
            "warning": "ATTENTION",
            "action_required": "ACTION REQUIRED",
        }
        label = labels.get(self.state, self.state.upper())
        return f"{self.name}: {label} – {self.message}"


def load_env_file(path: Path) -> dict[str, str]:
    """Load a minimal .env style file into a dictionary."""

    if not path.exists():
        return {}

    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export ") :].lstrip()

        key, sep, value = line.partition("=")
        if not sep:
            continue

        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        env[key] = value
    return env


def determine_withings_status(env: Mapping[str, str], token_path: Path) -> AuthStatus:
    """Return the current Withings authorisation status."""

    name = "Withings"

    if token_path.exists():
        try:
            token_data = json.loads(token_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return AuthStatus(
                name=name,
                state="action_required",
                message=(
                    f"{TOKEN_FILE_NAME} exists but could not be parsed. Delete the file and "
                    "re-authorise via `pete-e withings-auth-url` followed by "
                    "`pete-e withings-exchange-code <code>` to capture fresh tokens."
                ),
            )

        refresh_token = str(token_data.get("refresh_token") or "").strip()
        if refresh_token:
            updated = datetime.fromtimestamp(
                token_path.stat().st_mtime, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")
            return AuthStatus(
                name=name,
                state="ok",
                message=(
                    f"Refresh token stored in {TOKEN_FILE_NAME} (updated {updated}). "
                    "Run `pete-e refresh-withings` if you want to confirm the stored tokens."
                ),
            )

        return AuthStatus(
            name=name,
            state="action_required",
            message=(
                f"{TOKEN_FILE_NAME} is present but missing a refresh_token. "
                "Re-run `pete-e withings-auth-url` and `pete-e withings-exchange-code <code>` "
                "to capture a complete token set."
            ),
        )

    if env.get("WITHINGS_REFRESH_TOKEN"):
        return AuthStatus(
            name=name,
            state="warning",
            message=(
                "Refresh token only lives in .env. Persist it by running "
                "`pete-e refresh-withings` so future syncs can load "
                f"{TOKEN_FILE_NAME} without manual edits."
            ),
        )

    missing_fields = [
        key
        for key in ("WITHINGS_CLIENT_ID", "WITHINGS_CLIENT_SECRET", "WITHINGS_REDIRECT_URI")
        if not env.get(key)
    ]
    if missing_fields:
        field_list = ", ".join(missing_fields)
        return AuthStatus(
            name=name,
            state="action_required",
            message=(
                "Missing Withings developer settings in .env: "
                f"{field_list}. Create a Withings developer application and update the file before authorising."
            ),
        )

    return AuthStatus(
        name=name,
        state="action_required",
        message=(
            "No refresh token detected. Run `pete-e withings-auth-url`, approve the app, "
            "then call `pete-e withings-exchange-code <code>` to save the tokens."
        ),
    )


def determine_dropbox_status(env: Mapping[str, str]) -> AuthStatus:
    """Return the Dropbox credential status."""

    name = "Dropbox"
    required_keys = ["DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN"]
    missing = [key for key in required_keys if not env.get(key)]

    if not missing:
        return AuthStatus(
            name=name,
            state="ok",
            message=(
                "App key, secret, and refresh token are present. Tokens are long-lived, "
                "but re-run the Dropbox console flow if you ever rotate the app secret."
            ),
        )

    if missing == ["DROPBOX_REFRESH_TOKEN"]:
        return AuthStatus(
            name=name,
            state="action_required",
            message=(
                "App key and secret found, but no DROPBOX_REFRESH_TOKEN. Visit the Dropbox App Console, "
                "generate a scoped refresh token for your Health Auto Export app, and add it to .env."
            ),
        )

    missing_list = ", ".join(missing)
    return AuthStatus(
        name=name,
        state="action_required",
        message=(
            "Missing Dropbox OAuth values in .env: "
            f"{missing_list}. Create a Dropbox scoped app with files.read access, generate the key, secret, "
            "and refresh token, then update .env before running syncs."
        ),
    )


def main() -> int:
    """Entry point for the script."""

    project_root = Path.cwd()
    env_path = project_root / ".env"
    env = load_env_file(env_path)
    # Environment variables win over file-based values so ad-hoc overrides work.
    env.update({key: value for key, value in os.environ.items()})

    token_path = project_root / TOKEN_FILE_NAME

    statuses = [
        determine_withings_status(env, token_path),
        determine_dropbox_status(env),
    ]

    for status in statuses:
        print(status.format_line())

    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via tests on the helpers
    raise SystemExit(main())

