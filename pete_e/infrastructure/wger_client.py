"""
A unified client for all read and write interactions with the wger API v2.
This module consolidates logic from the previous implementations while offering
both API key and username/password authentication flows.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from pete_e.config import settings
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.decorators import retry_on_network_error
from pete_e.infrastructure.wger_url_policy import (
    INVALID_NEXT_URL,
    MAX_PAGES,
    PAGE_LIMIT_EXCEEDED,
    PAGINATION_CYCLE,
    REDIRECT_REJECTED,
    WgerUrlPolicy,
    WgerUrlPolicyError,
)


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
        """Initialize this object."""


class WgerClient:
    DEFAULT_CUSTOM_EXERCISE_CATEGORY = 9
    DEFAULT_CUSTOM_EXERCISE_LANGUAGE = 2

    def __init__(self, *, timeout: float | None = None):
        try:
            self._url_policy = WgerUrlPolicy.from_base(settings.WGER_BASE_URL)
        except WgerUrlPolicyError as exc:
            raise WgerError(str(exc)) from None

        self.base_url = self._url_policy.base_url
        self.api_root = self._url_policy.api_root

        self.api_key = settings.WGER_API_KEY
        self.username = getattr(settings, "WGER_USERNAME", None)
        self.password = getattr(settings, "WGER_PASSWORD", None)

        self.timeout = timeout or getattr(settings, "WGER_TIMEOUT", 10.0)
        self.max_retries = getattr(settings, "WGER_MAX_RETRIES", 3)
        self.backoff_base = getattr(settings, "WGER_BACKOFF_BASE", 0.5)

        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

        self.debug_api = bool(getattr(settings, "DEBUG_API", False))
        """Initialize this object."""

    def _get_jwt_token(self) -> str:
        if self._access_token and self._token_expiry and datetime.now(timezone.utc) < self._token_expiry:
            return self._access_token

        username = _unwrap_secret(self.username)
        password = _unwrap_secret(self.password)
        if not username or not password:
            raise WgerError("JWT auth requires WGER_USERNAME and WGER_PASSWORD.")

        url = self._url("/token")
        data = {"username": username, "password": password}
        response = requests.post(url, data=data, timeout=self.timeout, allow_redirects=False)
        if 300 <= response.status_code < 400:
            raise WgerError(REDIRECT_REJECTED, response)
        response.raise_for_status()

        token_data = response.json()
        self._access_token = token_data["access"]
        # JWT default expiry is 5 minutes; refresh slightly early.
        self._token_expiry = datetime.now(timezone.utc) + timedelta(minutes=4)
        return self._access_token
        """Perform get jwt token."""

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
        """Perform headers."""

    def _url(self, path: str) -> str:
        try:
            return self._url_policy.resolve_endpoint(path)
        except WgerUrlPolicyError as exc:
            raise WgerError(str(exc)) from None
        """Perform url."""

    def _should_retry(self, status: int) -> bool:
        return status in (408, 429, 500, 502, 503, 504)
        """Perform should retry."""

    def _request(self, method: str, path: str, **kwargs) -> Any:
        """Validate a request target before authentication, logging, or retries."""
        url = self._url(path)
        return self._request_validated(method, url, **kwargs)

    @retry_on_network_error(lambda self, status: self._should_retry(status), exception_types=(WgerError,))
    def _request_validated(self, method: str, path: str, **kwargs) -> Any:
        """Send an already-validated same-origin request with retry logic."""

        if self.debug_api:
            log_utils.debug(f"[wger.api] {method} {path} kwargs={kwargs}")

        try:
            kwargs["allow_redirects"] = False
            response = requests.request(
                method=method.upper(),
                url=path,
                headers=self._headers(),
                timeout=self.timeout,
                **kwargs,
            )
        except requests.exceptions.RequestException as exc:
            raise WgerError(f"{method} {path} failed: {exc!r}") from exc

        if self.debug_api:
            log_utils.debug(f"[wger.api] <- {response.status_code} {response.text[:500]}")

        if 300 <= response.status_code < 400:
            raise WgerError(REDIRECT_REJECTED, response)
        if response.status_code in (200, 201):
            return response.json()
        if response.status_code == 204:
            return None

        raise WgerError(f"{method} {path} failed with {response.status_code}", response)

    def ping(self) -> str:
        """Confirm authenticated connectivity to the wger API."""

        self._request("GET", "/routine/", params={"limit": 1})

        parsed = urlparse(self.base_url)
        host = parsed.netloc or parsed.path or self.base_url
        auth_mode = "api-key" if _unwrap_secret(self.api_key) else "jwt"
        return f"{host} ({auth_mode})"

    def get_all_pages(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Fetches and aggregates results from all pages of a paginated endpoint."""
        items: List[Dict[str, Any]] = []
        current_url = self._url(path)
        current_params = params.copy() if params else {}
        seen_urls: set[str] = set()
        page_count = 0

        while current_url:
            request_url = self._url_policy.request_url(current_url, current_params)
            if request_url in seen_urls:
                raise WgerError(PAGINATION_CYCLE)
            if page_count >= MAX_PAGES:
                raise WgerError(PAGE_LIMIT_EXCEEDED)
            seen_urls.add(request_url)

            data = self._request("GET", current_url, params=current_params)
            page_count += 1
            if not isinstance(data, dict):
                break

            items.extend(data.get("results", []))
            next_url = data.get("next")

            if next_url is None or next_url == "":
                break
            if not isinstance(next_url, str):
                raise WgerError(INVALID_NEXT_URL)

            try:
                current_url = self._url_policy.resolve_pagination(request_url, next_url)
            except WgerUrlPolicyError as exc:
                raise WgerError(str(exc)) from None
            current_params = {}
        return items

    def find_exercise_translation(
        self,
        *,
        name: str,
        language_id: int | None = None,
    ) -> Dict[str, Any] | None:
        params: Dict[str, Any] = {"name": name}
        if language_id is not None:
            params["language"] = language_id

        response = self._request("GET", "/exercise-translation/", params=params)
        results = response.get("results", []) if isinstance(response, dict) else []
        target = name.strip().lower()
        for item in results:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("name") or "").strip().lower()
            if candidate != target:
                continue
            if language_id is not None and item.get("language") != language_id:
                continue
            return item
        return None
        """Perform find exercise translation."""

    def ensure_custom_exercise(
        self,
        *,
        name: str,
        description: str,
        category_id: int | None = None,
        language_id: int | None = None,
        license_author: str = "Pete-E automation",
    ) -> int:
        resolved_category = category_id or self.DEFAULT_CUSTOM_EXERCISE_CATEGORY
        resolved_language = language_id or self.DEFAULT_CUSTOM_EXERCISE_LANGUAGE

        translation = self.find_exercise_translation(
            name=name,
            language_id=resolved_language,
        )
        if translation and translation.get("exercise") is not None:
            if str(translation.get("description") or "").strip() != description.strip():
                self._request(
                    "PATCH",
                    f"/exercise-translation/{translation['id']}/",
                    json={
                        "name": name,
                        "exercise": int(translation["exercise"]),
                        "description": description,
                        "language": resolved_language,
                        "license_author": license_author,
                    },
                )
            return int(translation["exercise"])

        exercise_payload = {
            "category": resolved_category,
            "muscles": [],
            "muscles_secondary": [],
            "equipment": [],
            "license_author": license_author,
        }
        exercise = self._request("POST", "/exercise/", json=exercise_payload)
        exercise_id = int(exercise["id"])

        translation_payload = {
            "name": name,
            "exercise": exercise_id,
            "description": description,
            "language": resolved_language,
            "license_author": license_author,
        }
        self._request("POST", "/exercise-translation/", json=translation_payload)
        return exercise_id
        """Perform ensure custom exercise."""

    # --- Catalog & Log Reading ---
    def get_workout_logs(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """Fetch workout logs covering an inclusive local-date range."""

        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

        local_timezone = ZoneInfo(str(getattr(settings, "USER_TIMEZONE", "Europe/London")))
        start_at = datetime.combine(start_date, time.min, tzinfo=local_timezone).astimezone(
            timezone.utc
        )
        end_before = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
            tzinfo=local_timezone,
        ).astimezone(timezone.utc)
        params = {
            "ordering": "date,id",
            "limit": 200,  # Max limit for wger
            "date__gte": start_at.isoformat(),
            "date__lt": end_before.isoformat(),
        }
        return self.get_all_pages("/workoutlog/", params=params)

    def get_weight_units(self) -> List[Dict[str, Any]]:
        """Return the configured routine weight-unit catalogue."""

        return self.get_all_pages("/setting-weightunit/", params={"ordering": "id"})

    def get_repetition_units(self) -> List[Dict[str, Any]]:
        """Return units that distinguish repetitions from time and distance."""

        return self.get_all_pages("/setting-repetitionunit/", params={"ordering": "id"})

    # --- Routine Writing ---
    def find_routine(self, name: str, start: date) -> Dict[str, Any] | None:
        """Return the exact routine for ``name`` and ``start``, if it exists."""

        start_text = start.isoformat()
        response = self._request(
            "GET",
            "/routine/",
            params={"name": name, "start": start_text},
        )
        results = response.get("results", []) if isinstance(response, dict) else []
        for routine in results:
            if not isinstance(routine, dict):
                continue
            if str(routine.get("name") or "") != name:
                continue
            if str(routine.get("start") or "")[:10] != start_text:
                continue
            return routine
        return None

    def find_or_create_routine(self, name: str, description: str, start: date, end: date) -> Dict[str, Any]:
        """Finds a routine by name and start date, creating it if it doesn't exist."""
        existing = self.find_routine(name, start)
        if existing is not None:
            return existing

        return self.create_routine(
            name=name,
            description=description,
            start=start,
            end=end,
        )

    def create_routine(self, name: str, description: str, start: date, end: date) -> Dict[str, Any]:
        """Create a new routine without reusing an existing name/date match."""

        payload = {"name": name, "description": description, "start": start.isoformat(), "end": end.isoformat()}
        return self._request("POST", "/routine/", json=payload)

    def update_routine(
        self,
        routine_id: int,
        *,
        name: str,
        description: str,
        start: date,
        end: date,
    ) -> Dict[str, Any]:
        """Promote a fully-written staging routine to its canonical identity."""

        payload = {
            "name": name,
            "description": description,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        return self._request("PATCH", f"/routine/{routine_id}/", json=payload)

    def delete_routine(self, routine_id: int) -> None:
        """Delete a complete routine, tolerating an already-removed object."""

        try:
            self._request("DELETE", f"/routine/{routine_id}/")
        except WgerError as exc:
            if exc.status_code == 404:
                log_utils.warn(f"Skipping stale wger routine {routine_id}: already deleted.")
                return
            raise

    def delete_all_days_in_routine(self, routine_id: int):
        """Wipes all Day objects associated with a routine."""
        days = self.get_all_pages("/day/", params={"routine": routine_id})
        for day in days:
            day_id = day["id"]
            try:
                self._request("DELETE", f"/day/{day_id}/")
            except WgerError as exc:
                if exc.status_code == 404:
                    log_utils.warn(
                        f"Skipping stale wger day {day_id} for routine {routine_id}: already deleted."
                    )
                    continue
                raise

    def create_day(self, routine_id: int, order: int, name: str) -> Dict[str, Any]:
        payload = {"routine": routine_id, "order": order, "name": name}
        return self._request("POST", "/day/", json=payload)
        """Perform create day."""

    def create_slot(self, day_id: int, order: int, comment: Optional[str] = None) -> Dict[str, Any]:
        payload = {"day": day_id, "order": order, "comment": (comment or "")[:200]}
        return self._request("POST", "/slot/", json=payload)
        """Perform create slot."""

    def create_slot_entry(
        self,
        slot_id: int,
        exercise_id: int,
        order: int = 1,
        *,
        entry_type: str | None = None,
        comment: str | None = None,
    ) -> Dict[str, Any]:
        payload = {"slot": slot_id, "exercise": exercise_id, "order": order}
        if entry_type:
            payload["type"] = entry_type
        if comment:
            payload["comment"] = comment[:100]
        return self._request("POST", "/slot-entry/", json=payload)
        """Perform create slot entry."""

    def set_config(self, config_type: str, slot_entry_id: int, iteration: int, value: Any, repeat: bool = False):
        """Generic method to post to sets-config, repetitions-config, etc."""
        endpoint_map = {
            "weight": "/weight-config/",
            "sets": "/sets-config/",
            "reps": "/repetitions-config/",
            "rest": "/rest-config/",
            "rir": "/rir-config/",
        }
        if config_type not in endpoint_map:
            raise ValueError(f"Invalid config_type: {config_type}")

        if config_type in {"sets", "rest"}:
            config_value: Any = int(value)
        else:
            config_value = str(value)

        payload = {
            "slot_entry": slot_entry_id,
            "iteration": iteration,
            "value": config_value,
            "operation": "r",
            "step": "na",
            "repeat": repeat,
        }
        self._request("POST", endpoint_map[config_type], json=payload)
    """Represent WgerClient."""
