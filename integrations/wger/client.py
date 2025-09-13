"""
Wger API client for Pete-E
Refactored from a procedural script to a class-based client.
It uses a centralized configuration service for credentials and API URLs.
"""

import requests
from datetime import datetime, timedelta, timezone

# Import the centralized settings object
from pete_e.config import settings
from pete_e.infra.log_utils import log_message


class WgerClient:
    """A client to interact with the Wger API."""

    def __init__(self):
        """Initializes the client with credentials from the settings."""
        self.api_key = settings.WGER_API_KEY
        self.base_url = settings.WGER_API_URL
        self.headers = {
            "Authorization": f"Token {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def fetch_logs(self, days: int = 1) -> list[dict]:
        """Fetch workout logs from Wger for the past N days."""
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
            r = requests.get(url, headers=self.headers, params=params, timeout=30)
            r.raise_for_status()
            js = r.json()
            results = js.get("results", [])
            log_message(f"Successfully fetched {len(results)} Wger log entries.")
            return results
        except requests.RequestException as e:
            log_message(f"Failed to fetch Wger logs: {e}", "ERROR")
            return []

    def get_logs_by_date(self, days: int = 1) -> dict[str, list[dict]]:
        """Return dict of logs keyed by date with clean exercise entries."""
        logs = self.fetch_logs(days=days)
        out: dict[str, list[dict]] = {}

        for log in logs:
            # The date can sometimes include timezone info, so we normalize it
            try:
                d = datetime.fromisoformat(log.get("date", "")).date().isoformat()
            except (ValueError, TypeError):
                continue

            row = {
                "exercise_id": log.get("exercise"),
                "sets": log.get("sets"),
                "reps": log.get("repetitions"),
                "weight": log.get("weight"),
                "rir": log.get("rir"),
                "rest_seconds": log.get("rest"),
            }
            out.setdefault(d, []).append(row)

        return out
