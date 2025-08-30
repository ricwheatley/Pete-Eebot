"""
wger_uploads.py
Uploads workouts from a schedule JSON to wger as dated workout sessions.

Usage:
  python integrations/wger/wger_uploads.py <schedule.json> [--dry-run]

Env:
  WGER_API_KEY   (required)  -> your wger API token (repo Secret)
  WGER_BASE_URL  (optional)  -> e.g. "https://wger.de/api/v2"
                               If unset or empty, defaults to https://wger.de/api/v2
"""

import json
import os
import sys
import time
from typing import Any, Dict, List

import requests


def _env_base_url() -> str:
    # Treat unset OR empty as default
    base = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").strip().rstrip("/")
    if not base.startswith("http"):
        print(f"ERROR: WGER_BASE_URL invalid: '{base}'")
        sys.exit(2)
    return base


BASE_URL = _env_base_url()
API_KEY = os.environ.get("WGER_API_KEY")

if not API_KEY:
    print("ERROR: WGER_API_KEY is not set.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Token {API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def post_json(endpoint: str, payload: Dict[str, Any], max_retries: int = 3, backoff: float = 2.0) -> Dict[str, Any]:
    """POST JSON with basic retries on transient errors."""
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
        except requests.RequestException as e:
            if attempt < max_retries:
                time.sleep(backoff * attempt)
                continue
            print(f"Request exception on {url}: {e}")
            raise

        if 200 <= r.status_code < 300:
            try:
                return r.json() if r.text else {}
            except ValueError:
                return {"status": r.status_code, "text": r.text}

        if r.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
            time.sleep(backoff * attempt)
            continue

        # Make hard failures obvious in the logs
        print(f"Request failed ({r.status_code}) for {url}: {r.text}")
        r.raise_for_status()

    return {}


def create_workoutsession(date_str: str, title: str, comment: str, duration_min: int | None) -> Dict[str, Any]:
    """
    Create a dated workout session.

    Known fields for /workoutsession/ include at least:
      - date (YYYY-MM-DD)
      - notes (string)
      - duration (integer minutes)   # optional but useful
    """
    payload: Dict[str, Any] = {
        "date": date_str,
        "notes": comment,
    }
    if duration_min:
        payload["duration"] = int(duration_min)

    return post_json("/workoutsession/", payload)


def load_schedule(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def summarize_entry(e: Dict[str, Any]) -> str:
    title = e.get("title", "Untitled")
    date_str = e.get("date", "YYYY-MM-DD")
    t = e.get("time")
    time_str = f" @ {t}" if t else ""
    return f"{date_str}: {title}{time_str}"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python integrations/wger/wger_uploads.py <schedule.json> [--dry-run]")
        sys.exit(2)

    schedule_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    print(f"[wger] Base URL: {BASE_URL}")
    print(f"[wger] Dry run: {'YES' if dry_run else 'NO'}")
    print(f"[wger] Reading schedule: {schedule_path}")

    data = load_schedule(schedule_path)
    entries: List[Dict[str, Any]] = data.get("entries", [])
    if not entries:
        print("No entries found in schedule JSON.")
        sys.exit(0)

    # Only upload 'weights' and 'class' (Blaze placeholders) as requested
    to_upload = [e for e in entries if e.get("kind") in ("weights", "class")]
    print(f"[wger] Entries in schedule: {len(entries)} | Eligible for upload (weights/class): {len(to_upload)}")

    created: List[Dict[str, Any]] = []

    for e in to_upload:
        date_str: str = e.get("date", "")
        title: str = e.get("title", "Workout")
        time_str = f" @ {e.get('time')}" if e.get("time") else ""
        duration = e.get("duration_min")
        rpe = e.get("rpe_target")
        details = e.get("details", {}) or {}

        bits: List[str] = []
        if duration:
            bits.append(f"{duration} min")
        if rpe:
            bits.append(f"RPE {rpe}")
        if details.get("notes"):
            bits.append(details["notes"])
        if details.get("exercises"):
            ex_lines = []
            for x in details["exercises"]:
                name = x.get("name", "Exercise")
                sets = x.get("sets", "?")
                reps = x.get("reps", "?")
                r = x.get("RPE", "—")
                ex_lines.append(f"- {name}: {sets} x {reps} @ RPE {r}")
            bits.append("Exercises:\n" + "\n".join(ex_lines))

        comment = f"{title}{time_str}"
        if bits:
            comment += " | " + " | ".join(bits)

        pretty = summarize_entry(e)
        if dry_run:
            print(f"[DRY RUN] Would create workoutsession: {pretty}")
            continue

        try:
            res = create_workoutsession(date_str, title, comment, duration)
            created.append({"date": date_str, "title": title, "id": res.get("id")})
            print(f"[OK] Created: {pretty} -> id={res.get('id')}")
        except Exception as ex:
            print(f"[ERROR] Failed to create: {pretty} — {ex}")

    print(json.dumps({"created": created}, indent=2))


if __name__ == "__main__":
    main()