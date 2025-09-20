# (Functional) Withings API client – interacts with Withings REST API for weight/bodyfat data. Manages OAuth tokens (refreshes and saves to `.withings_tokens.json`)

"""
Withings API client for Pete-E.
Now persists tokens in .withings_tokens.json so you don’t have to update .env manually.
"""

import json
import time
from pathlib import Path
import requests
from datetime import datetime, timedelta, timezone

from pydantic import SecretStr

from pete_e.config import settings
from pete_e.infrastructure.log_utils import log_message


def _unwrap_secret(value):
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


RATE_LIMIT_STATUS = 429
MAX_RATE_LIMIT_RETRIES = 3


class WithingsClient:
    """A client to interact with the Withings API."""

    TOKEN_FILE = Path(__file__).resolve().parent.parent.parent / ".withings_tokens.json"

    def __init__(self):
        """Initializes the client with credentials from settings or token file."""
        self.client_id = settings.WITHINGS_CLIENT_ID
        self.client_secret = _unwrap_secret(settings.WITHINGS_CLIENT_SECRET)
        self.redirect_uri = settings.WITHINGS_REDIRECT_URI

        # Try to load existing tokens from file
        self.access_token = None
        self.refresh_token = None

        if self.TOKEN_FILE.exists():
            try:
                with open(self.TOKEN_FILE) as f:
                    tokens = json.load(f)
                self.refresh_token = tokens.get("refresh_token")
                self.access_token = tokens.get("access_token")
                log_message("Loaded Withings tokens from file.", "INFO")
            except Exception as e:
                log_message(f"Failed to load tokens from file: {e}", "WARN")

        # Fallback to .env if no token file
        if not self.refresh_token:
            self.refresh_token = _unwrap_secret(settings.WITHINGS_REFRESH_TOKEN)
            log_message("Using refresh token from .env", "INFO")

        self.token_url = "https://wbsapi.withings.net/v2/oauth2"
        self.measure_url = "https://wbsapi.withings.net/measure"

    def _save_tokens(self, tokens: dict) -> None:
        """Persist tokens to disk."""
        with open(self.TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
        log_message("Saved Withings tokens to file.", "INFO")

    def _refresh_access_token(self):
        """Exchanges the refresh token for a new access token."""
        log_message("Refreshing Withings access token.", "INFO")
        data = {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": _unwrap_secret(self.client_secret),
            "refresh_token": _unwrap_secret(self.refresh_token),
        }
        backoff = 30
        last_response = None

        for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = requests.post(self.token_url, data=data, timeout=30)
            except requests.RequestException as exc:
                log_message(f"Withings token refresh request failed: {exc}", "ERROR")
                raise

            if response.status_code == RATE_LIMIT_STATUS:
                if attempt == MAX_RATE_LIMIT_RETRIES:
                    log_message("Withings token refresh hit rate limit repeatedly; giving up.", "ERROR")
                    response.raise_for_status()

                retry_after = response.headers.get("Retry-After")
                wait_seconds = None

                if retry_after:
                    try:
                        wait_seconds = int(float(retry_after))
                    except ValueError:
                        wait_seconds = None

                if wait_seconds is None:
                    wait_seconds = backoff

                log_message(
                    (
                        f"Withings token refresh received 429 (attempt {attempt}/{MAX_RATE_LIMIT_RETRIES}). "
                        f"Retrying in {wait_seconds}s."
                    ),
                    "WARN",
                )

                time.sleep(wait_seconds)
                backoff = min(wait_seconds * 2, 300)
                last_response = response
                continue

            response.raise_for_status()
            last_response = response
            break
        else:
            if last_response is not None:
                last_response.raise_for_status()
            raise RuntimeError("Withings token refresh failed after retries.")

        js = last_response.json()
        if js.get("status") != 0:
            raise RuntimeError(f"Withings token refresh failed: {js}")

        body = js["body"]
        self.access_token = body["access_token"]
        self.refresh_token = body["refresh_token"]

        # Save for next time
        self._save_tokens(body)
        log_message("Successfully refreshed Withings access token.", "INFO")

        return body

    def _fetch_measures(self, start: datetime, end: datetime) -> dict:
        """Fetches Withings measures for a given time window."""
        if not self.access_token:
            self._refresh_access_token()

        params = {
            "action": "getmeas",
            "meastypes": "1,6,76,77",  # weight, fat %, muscle, water
            "category": 1,
            "startdate": int(start.timestamp()),
            "enddate": int(end.timestamp()),
        }
        backoff = 30
        last_response = None

        for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = requests.get(
                    self.measure_url,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    params=params,
                    timeout=30,
                )
            except requests.RequestException as exc:
                log_message(f"Withings measures request failed: {exc}", "ERROR")
                raise

            if response.status_code == RATE_LIMIT_STATUS:
                if attempt == MAX_RATE_LIMIT_RETRIES:
                    log_message("Withings API rate limit hit repeatedly; giving up.", "ERROR")
                    response.raise_for_status()

                retry_after = response.headers.get("Retry-After")
                wait_seconds = None

                if retry_after:
                    try:
                        wait_seconds = int(float(retry_after))
                    except ValueError:
                        wait_seconds = None

                if wait_seconds is None:
                    wait_seconds = backoff

                log_message(
                    (
                        f"Withings API returned 429 (attempt {attempt}/{MAX_RATE_LIMIT_RETRIES}). "
                        f"Retrying in {wait_seconds}s."
                    ),
                    "WARN",
                )

                time.sleep(wait_seconds)
                backoff = min(wait_seconds * 2, 300)
                last_response = response
                continue

            response.raise_for_status()
            return response.json()

        if last_response is not None:
            last_response.raise_for_status()
        raise RuntimeError("Unexpected failure fetching Withings measures.")

    def get_summary(self, days_back: int = 1) -> dict:
        """
        Returns a summary dict for a given day.
        Includes: weight, fat %, muscle mass, and water %.
        """
        tz = timezone.utc
        today = datetime.now(tz).date()
        target_date = today - timedelta(days=days_back)
        start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)
        end = start + timedelta(days=1)

        js = self._fetch_measures(start, end)
        if js.get("status") != 0:
            raise RuntimeError(f"Withings fetch failed: {js}")

        measures = js.get("body", {}).get("measuregrps", [])
        if not measures:
            log_message(
                f"No Withings measures found for {target_date.isoformat()}.", "WARN"
            )
            return {"date": target_date.isoformat()}

        latest = measures[-1]
        row = {"date": target_date.isoformat()}

        def val(type_id: int):
            for m in latest.get("measures", []):
                if m.get("type") == type_id:
                    return m["value"] * (10 ** m.get("unit", 0))
            return None

        row["weight"] = round(val(1), 2) if val(1) is not None else None
        row["fat_percent"] = round(val(6), 2) if val(6) is not None else None
        row["muscle_mass"] = round(val(76), 2) if val(76) is not None else None
        row["water_percent"] = round(val(77), 2) if val(77) is not None else None

        log_message(
            f"Successfully fetched Withings summary for {target_date.isoformat()}.",
            "INFO",
        )
        return row







