#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pull recent Wger workout logs and save as JSON + CSV under integrations/wger/logs/.
Priority is to use the last routine id (routine/{id}/logs); if not available,
falls back to /workoutlog/.

Environment:
  WGER_API_KEY (required)
  WGER_BASE_URL (optional, default https://wger.de/api/v2)
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import requests

BASE = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").strip().rstrip("/")
API_KEY = os.environ.get("WGER_API_KEY")
HEADERS = {
    "Authorization": f"Token {API_KEY}" if API_KEY else "",
    "Accept": "application/json",
}

LOG_DIR = "integrations/wger/logs"
STATE_FILE = "integrations/wger/state/last_routine.json"

def die(msg: str, code: int = 1) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(code)

def fetch_all(url: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    next_url = url
    while next_url:
        r = requests.get(next_url, headers=HEADERS, params=params if next_url == url else None, timeout=60)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "results" in data:
            results.extend(data["results"])
            next_url = data.get("next")
        elif isinstance(data, list):
            results.extend(data)
            next_url = None
        else:
            break
    return results

def main() -> None:
    if not API_KEY:
        die("WGER_API_KEY not set")

    os.makedirs(LOG_DIR, exist_ok=True)
    today = datetime.utcnow().date()
    since = today - timedelta(days=35)  # last 5 weeks

    # Try routine-specific logs
    routine_id: Optional[int] = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as sf:
                routine_id = (json.load(sf) or {}).get("routine_id")
        except Exception:
            pass

    if routine_id:
        url = f"{BASE}/routine/{routine_id}/logs"
        print(f"[wger] Fetching logs via routine id={routine_id}")
        # Endpoint likely returns a list without pagination; handle both
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else data.get("results", [])
    else:
        # Fallback to workoutlog list
        print("[wger] Fetching logs via /workoutlog/")
        rows = fetch_all(f"{BASE}/workoutlog/", params={"limit": 200})

    # Filter by date >= since (date in ISO yyyy-mm-dd in field 'date' or 'start_time'?)
    def parse_date(x: str) -> Optional[datetime]:
        for key in ("date", "start_time", "created"):
            v = x.get(key) if isinstance(x, dict) else None
            try:
                if v:
                    return datetime.fromisoformat(v[:19])
            except Exception:
                continue
        return None

    filtered: List[Dict[str, Any]] = []
    for row in rows:
        d = None
        if isinstance(row, dict):
            d = row.get("date") or row.get("start_time") or row.get("created")
        date_obj = None
        try:
            if d:
                date_obj = datetime.fromisoformat(str(d)[:19])
        except Exception:
            pass
        if not date_obj or date_obj.date() < since:
            continue
        filtered.append(row)

    # Write JSON
    json_path = os.path.join(LOG_DIR, f"wger_logs_{today.isoformat()}.json")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(filtered, jf, ensure_ascii=False, indent=2)

    # Write CSV (best effort)
    csv_path = os.path.join(LOG_DIR, f"wger_logs_{today.isoformat()}.csv")
    # Flatten minimal fields if present
    fieldnames = ["date","routine_id","day_id","exercise_id","exercise_name","weight","repetitions","rir","rest","notes"]
    with open(csv_path, "w", encoding="utf-8", newline="") as cf:
        w = csv.DictWriter(cf, fieldnames=fieldnames)
        w.writeheader()
        for row in filtered:
            # These keys may vary; attempt to extract common ones
            w.writerow({
                "date": row.get("date") or row.get("start_time") or "",
                "routine_id": row.get("routine") or "",
                "day_id": row.get("day") or "",
                "exercise_id": row.get("exercise") or "",
                "exercise_name": (row.get("exercise_obj") or {}).get("name") if isinstance(row.get("exercise_obj"), dict) else "",
                "weight": row.get("weight") or "",
                "repetitions": row.get("repetitions") or "",
                "rir": row.get("rir") or "",
                "rest": row.get("rest") or "",
                "notes": row.get("notes") or "",
            })

    print(f"[wger] Wrote {json_path} and {csv_path}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
