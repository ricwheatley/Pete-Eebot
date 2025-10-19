"""
A unified client for all read and write interactions with the wger API v2.
This module consolidates logic from the previous implementations while offering
both API key and username/password authentication flows.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from pete_e.config import settings
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.decorators import retry_on_network_error


def _unwrap_secret(value: Any) -> Any:
    """Return the plain value for SecretStr instances."""
    if hasattr(value, "get_secret_value"):
        try:
            return value.get_secret_value()  # type: ignore[no-any-return]
        except TypeError:
            return value
    return value


class WgerError(RuntimeError):
    """Custom exception for Wger API errors."""

    def __init__(self, msg: str, resp: Optional[requests.Response] = None):
        super().__init__(msg)
        self.resp = resp
        self.status_code = None if resp is None else resp.status_code
        self.text = None if resp is None else (resp.text or "")


class WgerClient:
    def __init__(self, *, timeout: float | None = None):
        api_suffix = "/api/v2"
        raw_base = settings.WGER_BASE_URL.rstrip("/")

        if raw_base.lower().endswith(api_suffix):
            trimmed = raw_base[: -len(api_suffix)]
        else:
            trimmed = raw_base

        self.base_url = trimmed.rstrip("/") or trimmed
        if not self.base_url:
            raise WgerError("WGER_BASE_URL must include scheme and host.")

        self.api_root = f"{self.base_url}{api_suffix}"

        self.api_key = settings.WGER_API_KEY
        self.username = getattr(settings, "WGER_USERNAME", None)
        self.password = getattr(settings, "WGER_PASSWORD", None)

        self.timeout = timeout or getattr(settings, "WGER_TIMEOUT", 10.0)
        self.max_retries = getattr(settings, "WGER_MAX_RETRIES", 3)
        self.backoff_base = getattr(settings, "WGER_BACKOFF_BASE", 0.5)

        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

        self.debug_api = bool(getattr(settings, "DEBUG_API", False))

    def _get_jwt_token(self) -> str:
        if self._access_token and self._token_expiry and datetime.now(timezone.utc) < self._token_expiry:
            return self._access_token

        username = _unwrap_secret(self.username)
        password = _unwrap_secret(self.password)
        if not username or not password:
            raise WgerError("JWT auth requires WGER_USERNAME and WGER_PASSWORD.")

        url = f"{self.api_root}/token"
        data = {"username": username, "password": password}
        response = requests.post(url, data=data, timeout=self.timeout)
        response.raise_for_status()

        token_data = response.json()
        self._access_token = token_data["access"]
        # JWT default expiry is 5 minutes; refresh slightly early.
        self._token_expiry = datetime.now(timezone.utc) + timedelta(minutes=4)
        return self._access_token

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        api_key = _unwrap_secret(self.api_key)
        if api_key:
            headers["Authorization"] = f"Token {api_key}"
            return headers

        if self.username and self.password:
            headers["Authorization"] = f"Bearer {self._get_jwt_token()}"
            return headers

        raise WgerError("No authentication method configured for WgerClient.")

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path

        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self.api_root}{normalized}"

    def _should_retry(self, status: int) -> bool:
        return status in (408, 429, 500, 502, 503, 504)

    @retry_on_network_error(lambda self, status: self._should_retry(status), exception_types=(WgerError,))
    def _request(self, method: str, path: str, **kwargs) -> Any:
        """Internal request handler with retry logic."""
        url = self._url(path)

        if self.debug_api:
            log_utils.debug(f"[wger.api] {method} {url} kwargs={kwargs}")

        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                headers=self._headers(),
                timeout=self.timeout,
                **kwargs,
            )
        except requests.exceptions.RequestException as exc:
            raise WgerError(f"{method} {path} failed: {exc!r}") from exc

        if self.debug_api:
            log_utils.debug(f"[wger.api] <- {response.status_code} {response.text[:500]}")

        if response.status_code in (200, 201):
            return response.json()
        if response.status_code == 204:
            return None

        raise WgerError(f"{method} {path} failed with {response.status_code}", response)

    def get_all_pages(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Fetches and aggregates results from all pages of a paginated endpoint."""
        items: List[Dict[str, Any]] = []
        current_path = path
        current_params = params.copy() if params else {}

        while current_path:
            data = self._request("GET", current_path, params=current_params)
            if not isinstance(data, dict):
                break

            items.extend(data.get("results", []))
            next_url = data.get("next")

            if next_url:
                if next_url.startswith(self.api_root):
                    current_path = next_url.replace(self.api_root, "", 1)
                else:
                    current_path = next_url
                current_params = {}
            else:
                break
        return items

    # --- Catalog & Log Reading ---
    def get_workout_logs(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """Fetches workout logs within a date range."""
        params = {
            "ordering": "date",
            "limit": 200,  # Max limit for wger
            "date__gte": start_date.isoformat(),
            "date__lte": end_date.isoformat(),
        }
        return self.get_all_pages("/workoutlog/", params=params)

    # --- Routine Writing ---
    def find_or_create_routine(self, name: str, description: str, start: date, end: date) -> Dict[str, Any]:
        """Finds a routine by name and start date, creating it if it doesn't exist."""
        params = {"name": name, "start": start.isoformat()}
        existing = self._request("GET", "/routine/", params=params)
        if existing and existing.get("results"):
            return existing["results"][0]

        payload = {"name": name, "description": description, "start": start.isoformat(), "end": end.isoformat()}
        return self._request("POST", "/routine/", json=payload)

    def delete_all_days_in_routine(self, routine_id: int):
        """Wipes all Day objects associated with a routine."""
        days = self.get_all_pages("/day/", params={"routine": routine_id})
        for day in days:
            self._request("DELETE", f"/day/{day['id']}/")

    def create_day(self, routine_id: int, order: int, name: str) -> Dict[str, Any]:
        payload = {"routine": routine_id, "order": order, "name": name}
        return self._request("POST", "/day/", json=payload)

    def create_slot(self, day_id: int, order: int, comment: Optional[str] = None) -> Dict[str, Any]:
        payload = {"day": day_id, "order": order, "comment": (comment or "")[:200]}
        return self._request("POST", "/slot/", json=payload)

    def create_slot_entry(self, slot_id: int, exercise_id: int, order: int = 1) -> Dict[str, Any]:
        payload = {"slot": slot_id, "exercise": exercise_id, "order": order}
        return self._request("POST", "/slot-entry/", json=payload)

    def set_config(self, config_type: str, slot_entry_id: int, iteration: int, value: Any, repeat: bool = False):
        """Generic method to post to sets-config, repetitions-config, etc."""
        endpoint_map = {
            "sets": "/sets-config/",
            "reps": "/repetitions-config/",
            "rir": "/rir-config/",
        }
        if config_type not in endpoint_map:
            raise ValueError(f"Invalid config_type: {config_type}")

        payload = {
            "slot_entry": slot_entry_id,
            "iteration": iteration,
            "value": str(value),  # API expects string values for these
            "operation": "r",
            "step": "na",
            "repeat": repeat,
        }
        self._request("POST", endpoint_map[config_type], json=payload)
