# (Functional) Withings API client â€“ interacts with Withings REST API for weight/bodyfat data. Manages OAuth tokens (refreshes and saves to `.withings_tokens.json`)

"""
Withings API client for Pete-E.
Now persists tokens in .withings_tokens.json so you donâ€™t have to update .env manually.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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


@dataclass
class WithingsTokenState:
    requires_reauth: bool
    reason: Optional[str] = None
    last_refresh_utc: Optional[datetime] = None
    last_error_status: Optional[int] = None
    last_http_status: Optional[int] = None


class WithingsReauthRequired(RuntimeError):
    """Raised when the Withings refresh token is no longer valid."""

    def __init__(self, message: str, *, status: Optional[int] = None, http_status: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.http_status = http_status


class WithingsClient:
    """A client to interact with the Withings API."""

    TOKEN_FILE = Path(__file__).resolve().parent.parent.parent / ".withings_tokens.json"

    def __init__(self, request_timeout: float = 30.0):
        """Initializes the client with credentials from settings or token file."""
        self.client_id = settings.WITHINGS_CLIENT_ID
        self.client_secret = _unwrap_secret(settings.WITHINGS_CLIENT_SECRET)
        self.redirect_uri = settings.WITHINGS_REDIRECT_URI
        self._request_timeout = request_timeout

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
        self.user_url = "https://wbsapi.withings.net/v2/user"
        self._token_state = WithingsTokenState(requires_reauth=False)

    def _save_tokens(self, tokens: dict) -> None:
        """Persist tokens to disk."""
        with open(self.TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
        log_message("Saved Withings tokens to file.", "INFO")

    def get_token_state(self) -> WithingsTokenState:
        """Returns the current understanding of the refresh token state."""
        return self._token_state
    
    def ping(self) -> str:
        """Performs a lightweight Withings API call to confirm connectivity (user.metrics scope)."""
        if not self.access_token:
            self._refresh_access_token()

        def _reason(data: dict) -> str:
            body = data.get("body") if isinstance(data.get("body"), dict) else {}
            return str(
                data.get("error")
                or data.get("message")
                or body.get("message")
                or body.get("error")
                or data.get("status")
            )

        try:
            response = requests.post(
                self.measure_url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                data={"action": "getmeas", "meastype": 1, "category": 1, "limit": 1},
                timeout=self._request_timeout,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            payload = None
            try:
                payload = exc.response.json()
            except Exception:
                payload = None
            reason = _reason(payload or {})
            if payload and self._needs_reauth(reason, payload):
                self._token_state = WithingsTokenState(
                    requires_reauth=True,
                    reason=reason,
                    last_refresh_utc=self._token_state.last_refresh_utc,
                    last_error_status=payload.get("status") if isinstance(payload.get("status"), int) else None,
                    last_http_status=exc.response.status_code if exc.response else None,
                )
                raise WithingsReauthRequired(
                    reason,
                    status=payload.get("status") if isinstance(payload.get("status"), int) else None,
                    http_status=exc.response.status_code if exc.response else None,
                )
            raise RuntimeError(f"Withings ping failed: {reason or exc}") from exc
        except requests.RequestException as exc:
            log_message(f"Withings ping request failed: {exc}", "ERROR")
            raise RuntimeError(f"Withings ping request failed: {exc}") from exc

        payload = self._parse_json(response, context="ping")
        status = payload.get("status")
        if status == 0:
            self._token_state = WithingsTokenState(
                requires_reauth=False,
                reason=None,
                last_refresh_utc=self._token_state.last_refresh_utc,
                last_error_status=None,
                last_http_status=response.status_code,
            )
            return "metrics reachable"

        reason = _reason(payload)
        if self._needs_reauth(reason, payload):
            self._token_state = WithingsTokenState(
                requires_reauth=True,
                reason=reason,
                last_refresh_utc=self._token_state.last_refresh_utc,
                last_error_status=status if isinstance(status, int) else None,
                last_http_status=response.status_code,
            )
            raise WithingsReauthRequired(
                reason,
                status=status if isinstance(status, int) else None,
                http_status=response.status_code,
            )

        raise RuntimeError(f"Withings ping failed: {reason}")

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
        last_response: Optional[requests.Response] = None

        for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = requests.post(self.token_url, data=data, timeout=self._request_timeout)
            except requests.RequestException as exc:
                log_message(f"Withings token refresh request failed: {exc}", "ERROR")
                raise

            if response.status_code == RATE_LIMIT_STATUS:
                if attempt == MAX_RATE_LIMIT_RETRIES:
                    log_message("Withings token refresh hit rate limit repeatedly; giving up.", "ERROR")
                    self._handle_refresh_failure(response)
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

            if response.status_code >= 400:
                self._handle_refresh_failure(response)
                response.raise_for_status()

            last_response = response
            break
        else:
            if last_response is not None:
                self._handle_refresh_failure(last_response)
                last_response.raise_for_status()
            raise RuntimeError("Withings token refresh failed after retries.")

        payload = self._parse_json(last_response, context="token refresh")

        if payload.get("status") != 0:
            self._handle_refresh_failure(last_response, payload)
            raise RuntimeError(f"Withings token refresh failed: {payload}")

        body = payload.get("body", {})
        self.access_token = body.get("access_token")
        self.refresh_token = body.get("refresh_token")

        if not self.access_token or not self.refresh_token:
            raise RuntimeError("Withings token refresh returned incomplete credentials.")

        self._save_tokens(body)
        now_utc = datetime.now(timezone.utc)
        self._token_state = WithingsTokenState(
            requires_reauth=False,
            reason=None,
            last_refresh_utc=now_utc,
            last_error_status=None,
            last_http_status=None,
        )
        log_message("Successfully refreshed Withings access token.", "INFO")

        return body

    def _parse_json(self, response: requests.Response, *, context: str) -> dict:
        """Safely parses a JSON response, raising a runtime error if parsing fails."""
        try:
            return response.json()
        except ValueError as exc:
            log_message(f"Failed to parse Withings {context} response as JSON: {exc}", "ERROR")
            raise RuntimeError(f"Invalid JSON response from Withings during {context}.") from exc

    def _handle_refresh_failure(self, response: requests.Response, payload: Optional[dict] = None) -> None:
        """Updates token state and raises if the failure requires a manual reauthorisation."""
        if payload is None:
            try:
                payload = response.json()
            except ValueError:
                payload = None

        reason_parts = []
        status_code: Optional[int] = None

        if payload:
            status_code = payload.get("status") if isinstance(payload.get("status"), int) else status_code
            for key in ("error_description", "error", "message"):
                value = payload.get(key)
                if value:
                    reason_parts.append(str(value))
            body = payload.get("body")
            if isinstance(body, dict):
                body_message = body.get("message") or body.get("error")
                if body_message:
                    reason_parts.append(str(body_message))

        reason = " ".join(reason_parts).strip() or f"HTTP {response.status_code}"

        if self._needs_reauth(reason, payload):
            self._token_state = WithingsTokenState(
                requires_reauth=True,
                reason=reason,
                last_refresh_utc=self._token_state.last_refresh_utc,
                last_error_status=status_code,
                last_http_status=response.status_code,
            )
            raise WithingsReauthRequired(
                reason,
                status=status_code,
                http_status=response.status_code,
            )

        self._token_state = WithingsTokenState(
            requires_reauth=False,
            reason=None,
            last_refresh_utc=self._token_state.last_refresh_utc,
            last_error_status=status_code,
            last_http_status=response.status_code,
        )

    def _needs_reauth(self, reason: str, payload: Optional[dict]) -> bool:
        """Heuristically determines whether the refresh token is irrecoverable."""
        reason_lower = (reason or "").lower()
        if payload:
            status_val = payload.get("status")
            if isinstance(status_val, int) and status_val in {101, 106, 256, 264, 284, 285, 286, 300, 343, 601}:
                return True

            error_val = str(payload.get("error") or "").lower()
            if error_val in {"invalid_grant", "invalid_request", "invalid_token"}:
                return True

            body = payload.get("body")
            if isinstance(body, dict):
                body_msg = str(body.get("message") or body.get("error") or "").lower()
                if "invalid" in body_msg and "token" in body_msg:
                    return True
                if "refresh token" in body_msg and ("expired" in body_msg or "revoked" in body_msg):
                    return True

        if "invalid" in reason_lower and "token" in reason_lower:
            return True
        if "refresh token" in reason_lower and ("expired" in reason_lower or "revoked" in reason_lower):
            return True
        return False


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
                    timeout=self._request_timeout,
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

        weight_value = val(1)
        fat_value = val(6)
        muscle_value = val(76)
        water_value = val(77)

        row["weight"] = round(weight_value, 2) if weight_value is not None else None
        row["fat_percent"] = round(fat_value, 2) if fat_value is not None else None
        row["muscle_mass"] = round(muscle_value, 2) if muscle_value is not None else None
        if muscle_value is not None and weight_value not in (None, 0):
            row["muscle_percent"] = round((muscle_value / weight_value) * 100, 2)
        else:
            row["muscle_percent"] = None
        row["water_percent"] = round(water_value, 2) if water_value is not None else None

        log_message(
            f"Successfully fetched Withings summary for {target_date.isoformat()}.",
            "INFO",
        )
        return row















