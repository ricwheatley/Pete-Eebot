"""Read-only wger API client used during the daily sync.

The exporter/writer implementation lives in :mod:`wger_exporter_v3`; this
module is intentionally scoped to pulling historical workout logs so that the
orchestrator can reconcile completed sessions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests

from pete_e.config import settings
from pete_e.infrastructure.log_utils import log_message


def _resolve_secret(value: Any) -> str:
    """Return the underlying string for SecretStr or plain values."""

    if value is None:
        return ""
    get_secret = getattr(value, "get_secret_value", None)
    if callable(get_secret):
        try:
            return str(get_secret())
        except Exception:
            return ""
    return str(value)


class WgerClient:
    """Minimal helper to fetch workout log entries from wger."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: int = 30,
    ) -> None:
        resolved_base = base_url or getattr(settings, "WGER_BASE_URL", "https://wger.de/api/v2")
        self.base_url = resolved_base.rstrip("/")

        resolved_token = token or _resolve_secret(getattr(settings, "WGER_API_KEY", None))
        self.api_key = resolved_token.strip()
        self.timeout = timeout

        self.headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            self.headers["Authorization"] = f"Token {self.api_key}"

    def fetch_logs(self, days: int = 1) -> List[Dict[str, Any]]:
        """Fetch workout logs from wger for the past *days* window."""

        if not self.api_key:
            log_message("WGER_API_KEY not set. Skipping Wger log fetch.", "WARN")
            return []

        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days)

        url = f"{self.base_url}/workoutlog/"
        params = {
            "ordering": "-date",
            "limit": 200,
            "date_after": start.isoformat(),
            "date_before": end.isoformat(),
        }

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            log_message(f"Failed to fetch Wger logs: {exc}", "ERROR")
            return []

        payload = response.json() if response.content else {}
        results = payload.get("results", []) if isinstance(payload, dict) else []
        log_message(f"Successfully fetched {len(results)} Wger log entries.")
        return results

    def get_logs_by_date(self, days: int = 1) -> Dict[str, List[Dict[str, Any]]]:
        """Return logs keyed by ISO date with normalised fields."""

        logs = self.fetch_logs(days=days)
        grouped: Dict[str, List[Dict[str, Any]]] = {}

        for log in logs:
            try:
                log_date = datetime.fromisoformat(str(log.get("date", ""))).date().isoformat()
            except (TypeError, ValueError):
                continue

            entry = {
                "exercise_id": log.get("exercise"),
                "sets": log.get("sets"),
                "reps": log.get("repetitions"),
                "weight": log.get("weight"),
                "rir": log.get("rir"),
                "rest_seconds": log.get("rest"),
            }
            grouped.setdefault(log_date, []).append(entry)

        return grouped
