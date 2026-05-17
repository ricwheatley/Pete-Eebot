# OAuth helper for Withings. Runtime OAuth tokens use WITHINGS_TOKEN_FILE when configured.


import os
import requests
import json
from pathlib import Path

from pydantic import SecretStr
from urllib.parse import urlencode

from pete_e.config import get_env, settings
from pete_e.infrastructure.log_utils import log_message
def _unwrap_secret(value):
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value
    """Perform unwrap secret."""

DEFAULT_TOKEN_FILE = Path.home() / ".config" / "pete_eebot" / ".withings_tokens.json"


def configured_withings_token_file() -> Path:
    raw_path = get_env("WITHINGS_TOKEN_FILE", None)
    if raw_path:
        return Path(str(raw_path)).expanduser()
    return DEFAULT_TOKEN_FILE


TOKEN_FILE = configured_withings_token_file()

AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"

def build_authorize_url():
    params = {
        "response_type": "code",
        "client_id": settings.WITHINGS_CLIENT_ID,
        "redirect_uri": settings.WITHINGS_REDIRECT_URI,
        "scope": "user.metrics",  # adjust scopes if needed
        "state": "peteebot"
    }
    return f"{AUTH_URL}?{urlencode(params)}"
    """Perform build authorize url."""

def exchange_code_for_tokens(code: str):
    data = {
        "action": "requesttoken",
        "grant_type": "authorization_code",
        "client_id": settings.WITHINGS_CLIENT_ID,
        "client_secret": _unwrap_secret(settings.WITHINGS_CLIENT_SECRET),
        "code": code,
        "redirect_uri": settings.WITHINGS_REDIRECT_URI,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    js = r.json()
    if js.get("status") != 0:
        raise RuntimeError(f"Token request failed: {js}")

    tokens = js["body"]

    # Save to file
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    # Lock down permissions to avoid leaking OAuth credentials.
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError as exc:
        log_message(f"Could not set permissions on {TOKEN_FILE}: {exc}", "WARN")

    return tokens
    """Perform exchange code for tokens."""

if __name__ == "__main__":
    print("Step 1: Visit this URL in your browser and approve access:")
    print(build_authorize_url())
    print()
    code = input("Step 2: Paste the ?code=... value from the redirect URL here: ").strip()
    tokens = exchange_code_for_tokens(code)
    print("\n✅ Success! Here are your tokens:")
    print(f"Access token:  {tokens['access_token']}")
    print(f"Refresh token: {tokens['refresh_token']}")
    print("\n👉 Paste the refresh token into your .env as WITHINGS_REFRESH_TOKEN")

