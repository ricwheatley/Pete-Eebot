"""
Wger API client for Pete-E
Refactored from sync_wger_logs.py – no legacy artefacts, returns clean dicts.
"""

Import os
import requests
from datetime import datetime, timedelta, timezone

API_KEY = os.getenv("WGER_API_KEY")
BASE_URL = (os.getenv("WGER_BASE_URL") or "https://wger.de/api/v2").strip().strip("/")
HEADERS = {
    "Authorization": f"Token {API_KEY}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

def fetch_logs(days: int = 1):
    """Fatch workout logs from Wger for the past N days."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)

    url = f"{BASE_URL}/workoutlog/"
    params = {
        "ordering": "-date",
        "limit": 200,
        "date_after": start.isoformat(),
        "date_before": end.isoformat(),
    }

    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    return js.get("results", [])


def get_wger_logs(days: int = 1) -> dict:
    """Return dict of logs keyed by date with clean exercise entries."""
    logs = fetch_logs(days=days)
    out = {}
    for log in logs:
        d = log.get("date")
        if not d:
            continue
        row = {
            "exercise_id": log.get("exercise"),
            "sets": log.get("sets"),
            "reps": log.get("repetitions"),
            "weight": log.get("weight"),
            "rir": log.get("rir"),
            "rest_seconds": log.get("rest"),
        }
        out.setdefault(d, [])
        out[d].append(row)
    return out
