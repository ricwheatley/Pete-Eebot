#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sync Wger workout logs (past 7 days) – JSON only.

Writes:
  docs/wger/days/<YYYY-MM-DD>.json   # raw logs enriched with exercise name/category
  docs/wger/daily.json               # latest day’s logs
  docs/wger/history.json             # all days seen (dict keyed by date)

Set WGER_API_KEY in env.
"""

from __future__ import annotations
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import json
import os
import requests
from typing import Optional, Any, Dict, List

API_KEY = os.getenv("WGER_API_KEY")
if not API_KEY:
    print("WGER_API_KEY not set", flush=True)
    exit(1)

BASE = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").strip().rstrip("/")
HDRS = {"Authorization": f"Token {API_KEY}", "Accept": "application/json"}

DAYS_DIR    = Path("docs/wger/days").resolve()
HISTORY_P   = Path("docs/wger/history.json").resolve()
DAILY_P     = Path("docs/wger/daily.json").resolve()
CATALOG_P   = Path("integrations/wger/catalog/exercises_en.json").resolve()

def session_with_retries(total=5, backoff=0.6) -> requests.Session:
    s = requests.Session()
    retry = requests.packages.urllib3.util.retry.Retry(
        total=total, backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"])
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

def write_json(p: Path, payload: Any):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def fetch_paginated(s: requests.Session, url: str) -> Optional[List[dict]]:
    results: List[dict] = []
    next_url = url
    while next_url:
        r = s.get(next_url, headers=HDRS, timeout=30)
        if not r.ok:
            print(f"Error fetching {next_url}: {r.status_code} {r.text[:200]}")
            return None
        data = r.json()
        if isinstance(data, dict) and "results" in data:
            results.extend(data["results"])
            next_url = data.get("next")
        else:
            results.extend(data if isinstance(data, list) else [data])
            next_url = None
    return results

def load_exercise_catalog() -> Dict[int, Dict[str,str]]:
    out = {}
    if CATALOG_P.exists():
        try:
            data = json.loads(CATALOG_P.read_text(encoding="utf-8"))
            for row in data:
                ex_id = int(row.get("id"))
                out[ex_id] = {"name": row.get("name",""), "category": row.get("category","")}
        except Exception:
            pass
    return out

def main():
    s = session_with_retries()
    DAYS_DIR.mkdir(parents=True, exist_ok=True)
    catalog = load_exercise_catalog()

    # Fetch exercise info? Already loaded from catalog
    # Fetch logs (last 7 days)
    logs_url = f"{BASE}/workoutlog/?limit=200&ordering=-date"
    all_logs = fetch_paginated(s, logs_url)
    if all_logs is None:
        write_json(DAILY_P, [])
        print("wger: API unavailable, wrote empty daily.json")
        return

    today = datetime.now().date()
    start = today - timedelta(days=6)
    recent: List[dict] = []
    def parse_date(d: str) -> Optional[datetime.date]:
        try:
            return datetime.fromisoformat(d[:10]).date()
        except Exception:
            return None

    for log in all_logs:
        d_str = (log.get("date") or log.get("created") or "")
        d = parse_date(d_str)
        if d and start <= d <= today:
            log["_date"] = d.isoformat()
            recent.append(log)

    # Group by date and enrich names/categories
    by_day: Dict[str, List[dict]] = defaultdict(list)
    for log in recent:
        d = log["_date"]
        ex_id = log.get("exercise")
        details = catalog.get(int(ex_id)) if isinstance(ex_id, int) else {}
        log["exercise_name"] = details.get("name") or f"Exercise {ex_id}"
        log["category"]      = details.get("category") or "N/A"
        by_day[d].append(log)

    # Read existing history (dict keyed by date)
    history: Dict[str, List[dict]] = {}
    if HISTORY_P.exists():
        try:
            history = json.loads(HISTORY_P.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = {}

    # Write per-day and update history
    for d, logs in by_day.items():
        write_json(DAYS_DIR / f"{d}.json", logs)
        history[d] = logs

    write_json(HISTORY_P, history)

    if by_day:
        latest = max(by_day.keys())
        write_json(DAILY_P, by_day[latest])
        print(f"wger: wrote daily.json for {latest}")
    else:
        write_json(DAILY_P, [])
        print("wger: no logs in last 7 days, wrote empty daily.json")

if __name__ == "__main__":
    main()
