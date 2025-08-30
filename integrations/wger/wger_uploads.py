"""
wger_uploads.py
Uploads workouts from a schedule JSON to wger as dated workout sessions
AND can repair existing sessions to ensure numeric fields aren't null.

Usage:
  # create sessions
  python integrations/wger/wger_uploads.py <schedule.json> [--dry-run]

  # repair sessions that already exist for the dates in the JSON (set numeric defaults)
  python integrations/wger/wger_uploads.py <schedule.json> --repair

Env:
  WGER_API_KEY   (required)  -> your wger API token (repo Secret)
  WGER_BASE_URL  (optional)  -> e.g. "https://wger.de/api/v2" (defaults if unset/empty)
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests


def _env_base_url() -> str:
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


def _req(method: str, endpoint: str, *, params: Dict[str, Any] | None = None,
         payload: Dict[str, Any] | None = None, max_retries: int = 3, backoff: float = 2.0) -> requests.Response:
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.request(method.upper(), url, headers=HEADERS, params=params, json=payload, timeout=30)
        except requests.RequestException as e:
            if attempt < max_retries:
                time.sleep(backoff * attempt)
                continue
            raise
        if 200 <= r.status_code < 300:
            return r
        if r.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
            time.sleep(backoff * attempt)
            continue
        # make hard failures obvious
        print(f"{method} {url} -> {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
    return r  # type: ignore[unreachable]


def post_json(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = _req("POST", endpoint, payload=payload)
    try:
        return r.json() if r.text else {}
    except ValueError:
        return {"status": r.status_code, "text": r.text}


def get_json(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = _req("GET", endpoint, params=params)
    return r.json()


def patch_json(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = _req("PATCH", endpoint, payload=payload)
    return r.json() if r.text else {}


def create_workoutsession(date_str: str, title: str, comment: str, duration_min: Optional[int]) -> Dict[str, Any]:
    """
    Create a dated workout session. To avoid nulls crashing the mobile app,
    we always send numeric defaults for duration/energy/distance.
    """
    payload: Dict[str, Any] = {
        "date": date_str,
        "notes": comment,
        "duration": int(duration_min) if duration_min is not None else 1,  # avoid null; tiny default if needed
        "energy": 0,     # kcal
        "distance": 0,   # meters
        # "feeling": 3,  # optional (1-5). Uncomment if you want a neutral default.
    }
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


def ensure_non_null_numeric(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a PATCH payload that fills any null numeric fields with safe defaults.
    Only include fields that are actually null to avoid unnecessary writes.
    """
    patch: Dict[str, Any] = {}
    if session.get("duration") is None:
        patch["duration"] = 1
    if session.get("energy") is None:
        patch["energy"] = 0
    if session.get("distance") is None:
        patch["distance"] = 0
    return patch


def repair_sessions_for_dates(dates: List[str]) -> None:
    """
    For each date in 'dates', GET sessions and PATCH null numeric fields.
    """
    fixed = 0
    checked = 0
    for d in dates:
        # The API commonly supports filtering by date
        data = get_json("/workoutsession/", params={"date": d})
        results = data.get("results") or data  # handle both list or paginated dict
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        if not isinstance(results, list):
            results = []
        for s in results:
            checked += 1
            sess_id = s.get("id")
            patch = ensure_non_null_numeric(s)
            if patch and sess_id:
                patch_json(f"/workoutsession/{sess_id}/", patch)
                fixed += 1
                print(f"[REPAIR] Patched session {sess_id} on {d}: {patch}")
    print(f"[REPAIR] Checked {checked} sessions, fixed {fixed} with null numeric fields.")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python integrations/wger/wger_uploads.py <schedule.json> [--dry-run|--repair]")
        sys.exit(2)

    schedule_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    do_repair = "--repair" in sys.argv

    print(f"[wger] Base URL: {BASE_URL}")
    print(f"[wger] Mode: {'REPAIR' if do_repair else ('DRY-RUN' if dry_run else 'UPLOAD')}")
    print(f"[wger] Reading schedule: {schedule_path}")

    data = load_schedule(schedule_path)
    entries: List[Dict[str, Any]] = data.get("entries", [])
    if not entries:
        print("No entries found in schedule JSON.")
        sys.exit(0)

    # subset of entries we actually manage in wger
    to_manage = [e for e in entries if e.get("kind") in ("weights", "class")]

    if do_repair:
        # Collect dates from the JSON (unique) and patch any sessions with null numerics
        dates = sorted({e.get("date") for e in to_manage if e.get("date")})
        repair_sessions_for_dates(dates)
        return

    print(f"[wger] Entries in schedule: {len(entries)} | Eligible (weights/class): {len(to_manage)}")

    created: List[Dict[str, Any]] = []
    for e in to_manage:
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