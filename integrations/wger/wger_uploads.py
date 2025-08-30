#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Upload day-by-day sessions to Wger via the REST API.

Expected JSON schedule format (list of entries):
[
  {
    "date": "2025-09-01",
    "type": "weights" | "class" | "rest",
    "title": "Weights — Lower Body" | "Blaze HIIT @ 06:15" | "Rest",
    "duration": 45,                 # minutes (int); we will default to 45 if missing
    "feeling": 3,                   # 1..5 scale; we default to 3 if missing
    "notes": "optional notes text"  # optional string
  },
  ...
]

Notes:
- We post to /workoutsession/ (confirmed by API root).
- We always send numeric duration & feeling to avoid null->num cast issues in the mobile app.
- 'rest' entries are skipped by default (no session created).
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

import requests

# ---------- Config & Headers ----------

def base_url() -> str:
    # Default to the public service; allow override via env (e.g., self-hosted instance).
    base = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").strip().rstrip("/")
    return base

def api_headers() -> Dict[str, str]:
    api_key = os.environ.get("WGER_API_KEY", "").strip()
    if not api_key:
        print("[ERROR] WGER_API_KEY is not set in the environment.", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

# ---------- HTTP helpers ----------

def get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{base_url()}{path}"
    r = requests.get(url, headers=api_headers(), params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def post_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base_url()}{path}"
    r = requests.post(url, headers=api_headers(), json=payload, timeout=30)
    # If the DRF browsable API returns HTML on error, show snippet
    if not r.ok:
        body = r.text
        snippet = body[:500].replace("\n", " ")
        print(f"Request failed ({r.status_code}) for {url}: {snippet}", file=sys.stderr)
    r.raise_for_status()
    return r.json() if r.text.strip() else {}

# ---------- Domain helpers ----------

def normalize_entry(e: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convert a schedule entry into a POST payload for /workoutsession/.
    Returns None for entries we intentionally skip (e.g., rest days).
    """
    entry_type = (e.get("type") or "").lower().strip()
    if entry_type == "rest":
        return None

    date = e.get("date")
    if not date:
        print("[WARN] Skipping entry without 'date':", e, file=sys.stderr)
        return None

    # Ensure numeric fields are present to avoid nulls in app model:
    duration = e.get("duration")
    try:
        duration = int(duration) if duration is not None else 45
    except Exception:
        duration = 45

    feeling = e.get("feeling")
    try:
        feeling = int(feeling) if feeling is not None else 3
    except Exception:
        feeling = 3

    # Clamp feeling to 1..5 if present
    if feeling < 1:
        feeling = 1
    if feeling > 5:
        feeling = 5

    title = e.get("title") or "Session"
    notes = e.get("notes") or ""

    # Keep notes concise but informative
    auto_notes = f"{title} — planned via automation"
    if notes:
        combined_notes = f"{auto_notes}\n\n{notes}"
    else:
        combined_notes = auto_notes

    payload = {
        # Keys derived from the server-side model (workoutsession):
        "date": date,          # YYYY-MM-DD
        "duration": duration,  # minutes (int)
        "feeling": feeling,    # 1..5 (int)
        "notes": combined_notes
    }

    return payload

def create_session(payload: Dict[str, Any], dry_run: bool = False) -> Optional[Dict[str, Any]]:
    if dry_run:
        print(f"[DRY-RUN] Would POST to /workoutsession/: {json.dumps(payload, ensure_ascii=False)}")
        return None

    try:
        res = post_json("/workoutsession/", payload)
        created_id = res.get("id")
        print(f"[OK] Created session {created_id} on {payload.get('date')} — duration {payload.get('duration')} min, feeling {payload.get('feeling')}")
        return res
    except requests.HTTPError as err:
        print(f"[ERROR] Failed to create: {payload.get('date')}: {err}", file=sys.stderr)
        return None

# ---------- Main ----------

def load_schedule(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Schedule JSON must be a list of entries.")
    return data

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python integrations/wger/wger_uploads.py <schedule.json> [--dry-run]", file=sys.stderr)
        sys.exit(2)

    schedule_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    # Informational banner
    print(f"[wger] Base URL: {base_url()}")
    print(f"[wger] Dry run: {'YES' if dry_run else 'NO'}")
    print(f"[wger] Reading schedule: {schedule_path}")

    entries = load_schedule(schedule_path)
    print(f"[wger] Entries in schedule: {len(entries)}")

    to_upload = []
    for e in entries:
        payload = normalize_entry(e)
        if payload is not None:
            to_upload.append(payload)

    print(f"[wger] Eligible for upload (non-rest): {len(to_upload)}")

    ok = 0
    for p in to_upload:
        if create_session(p, dry_run=dry_run) is not None or dry_run:
            ok += 1

    print(f"[wger] Done. {'Would create' if dry_run else 'Created'} {ok} session(s).")

if __name__ == "__main__":
    main()