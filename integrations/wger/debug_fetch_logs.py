#!/usr/bin/env python3
import os
import json
import requests
import pathlib

API_KEY = os.getenv("WGER_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing WGER_API_KEY environment variable")

BASE = "https://wger.de/api/v2"
HDRS = {
    "Authorization": f"Token {API_KEY}",
    "Accept": "application/json"
}

DOCS_DIR = pathlib.Path("docs/wger/days")


def fetch_paginated(url: str):
    """Fetch all pages from a WGER endpoint."""
    results = []
    next_url = url
    while next_url:
        r = requests.get(next_url, headers=HDRS, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "results" in data:
            results.extend(data["results"])
            next_url = data.get("next")
        else:
            results.extend(data)
            next_url = None
    return results


def fetch_logs_for_date(date_str: str):
    """Fetch workout logs for a given date (YYYY-MM-DD)."""
    url = f"{BASE}/workoutlog/?date={date_str}"
    logs = fetch_paginated(url)
    return logs


if __name__ == "__main__":
    # Hard-coded date: 2025-09-08
    date_str = "2025-09-08"

    print(f"Fetching WGER logs for {date_str}...")
    logs = fetch_logs_for_date(date_str)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DIR / f"{date_str}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)

    print(f"Saved {len(logs)} logs to {out_path}")
