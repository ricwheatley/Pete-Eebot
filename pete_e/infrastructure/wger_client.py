# pete_e/infrastructure/wger_client.py
"""
A unified client for all read and write interactions with the wger API v2.
This module consolidates logic from the previous wger_client.py and wger_exporter.py.
"""
from __future__ import annotations
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from pete_e.config import settings
from pete_e.infrastructure import log_utils

class WgerError(RuntimeError):
    """Custom exception for Wger API errors."""
    def __init__(self, msg: str, resp: Optional[requests.Response] = None):
        super().__init__(msg)
        self.resp = resp
        self.status_code = None if resp is None else resp.status_code
        self.text = None if resp is None else (resp.text or "")

class WgerClient:
    """Handles all communication with the wger API v2."""

    def __init__(self, debug_api: bool = False):
        base_url = str(settings.WGER_BASE_URL).rstrip("/")
        if base_url.endswith("/api/v2"):
            base_url = base_url[:-len("/api/v2")]
        self.base_url = base_url
        
        token = str(settings.WGER_API_KEY)
        if not token:
            raise WgerError("WGER_API_KEY is not set")
        self.token = token
        
        self.timeout = 30
        self.max_retries = 3
        self.backoff_base = 0.75
        self.debug_api = debug_api

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Token {self.token}", "Accept": "application/json", "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v2{path if path.startswith('/') else '/' + path}"

    def _should_retry(self, status: int) -> bool:
        return status in (408, 429, 500, 502, 503, 504)

    def _request(self, method: str, path: str, **kwargs) -> Any:
        """Internal request handler with retry logic."""
        url = self._url(path)
        for attempt in range(self.max_retries):
            try:
                if self.debug_api:
                    log_utils.debug(f"[wger.api] {method} {url} kwargs={kwargs}")
                
                response = requests.request(method=method.upper(), url=url, headers=self._headers(), timeout=self.timeout, **kwargs)
                
                if self.debug_api:
                    log_utils.debug(f"[wger.api] <- {response.status_code} {response.text[:500]}")

                if response.status_code in (200, 201):
                    return response.json()
                if response.status_code == 204:
                    return None
                
                if not self._should_retry(response.status_code):
                    raise WgerError(f"{method} {path} failed with {response.status_code}", response)
                
                # If retry is needed, wait and continue loop
                sleep_for = self.backoff_base * (2 ** attempt)
                log_utils.warn(f"[wger.api] transient {response.status_code} on {method} {path}, retrying in {sleep_for:.2f}s...")
                time.sleep(sleep_for)

            except requests.exceptions.RequestException as exc:
                if attempt == self.max_retries - 1:
                    raise WgerError(f"{method} {path} failed after retries: {exc!r}") from exc
                sleep_for = self.backoff_base * (2 ** attempt)
                log_utils.warn(f"[wger.api] network error on {method} {path}: {exc!r}, retrying in {sleep_for:.2f}s...")
                time.sleep(sleep_for)

        raise WgerError(f"{method} {path} failed after all retries.")

    def get_all_pages(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Fetches and aggregates results from all pages of a paginated endpoint."""
        items: List[Dict[str, Any]] = []
        current_path = path
        current_params = params.copy() if params else {}
        
        while current_path:
            data = self._request("GET", current_path, params=current_params)
            if not isinstance(data, dict): break
            
            items.extend(data.get("results", []))
            next_url = data.get("next")
            
            if next_url:
                # The next URL contains the full path and params, so we reset them
                current_path = next_url.replace(self.base_url, "")
                current_params = {} 
            else:
                break
        return items

    # --- Catalog & Log Reading ---
    def get_workout_logs(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """Fetches workout logs within a date range."""
        params = {
            "ordering": "date",
            "limit": 200, # Max limit for wger
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
            "value": str(value), # API expects string values for these
            "operation": "r",
            "step": "na",
            "repeat": repeat,
        }
        self._request("POST", endpoint_map[config_type], json=payload)