#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Withings sync, JSON-only – no raw snapshots.

This script pulls the previous day's Withings measurements (weight, fat %, muscle, water) using the
OAuth2 refresh token flow and writes summarised JSON files into the repository's docs/withings
folder.  It does **not** write any CSVs or raw API snapshots.

Outputs:
  - docs/withings/days/<YYYY-MM-DD>.json  – one file per day, keyed by date
  - docs/withings/daily.json               – latest day’s record
  - docs/withings/history.json             – rolling 90-day history (array of day records)

Environment variables required:
  WITHINGS_CLIENT_ID       – your Withings API client ID
  WITHINGS_CLIENT_SECRET   – your Withings API client secret
  WITHINGS_REDIRECT_URI    – the OAuth2 redirect URI
  WITHINGS_REFRESH_TOKEN   – the stored Withings refresh token
Optional:
  WITHINGS_DAYS_BACK       – number of days to look back (default 14) when searching for valid data

Usage:
  python withings_sync.py              # assumes refresh token is set in the environment
  python withings_sync.py --code=<...> # first-run: exchange an authorisation code for tokens locally

This script should be run daily via CI; it computes yesterday in Europe/London time, refreshes the
access token, fetches measures for that 24-hour window, and updates the JSON artefacts.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any

import requests
from zoneinfo import ZoneInfo


TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
MEASURE_URL = "https://wbsapi.withings.net/measure"

CLIENT_ID = os.getenv("WITHINGS_CLIENT_ID")
CLIENT_SECRET = os.getenv("WITHINGS_CLIENT_SECRET")
REDIRECT_URI = os.getenv("WITHINGS_REDIRECT_URI")
REFRESH_TOKEN = os.getenv("WITHINGS_REFRESH_TOKEN")
DAYS_BACK = int(os.getenv("WITHINGS_DAYS_BACK", "14"))

BASE = Path("docs/withings")
DAYS_DIR = BASE / "days"
DAILY_PATH = BASE / "daily.json"
HISTORY_PATH = BASE / "history.json"
DAYS_DIR.mkdir(parents=True, exist_ok=True)


def session_with_retries(total: int = 5, backoff: float = 0.6) -> requests.Session:
    """Return a requests.Session configured with automatic retries for transient errors."""
    s = requests.Session()
    retry = requests.packages.urllib3.util.retry.Retry(
        total=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def token_exchange(s: requests.Session, *, code: Optional[str] = None, refresh_token: Optional[str] = None) -> dict:
    """Exchange an authorisation code or refresh token for an access token."""
    data = {
        "action": "requesttoken",
        "client_id": CLIENT_ID or "",
        "client_secret": CLIENT_SECRET or "",
    }
    if code:
        data.update({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI or "",
        })
    elif refresh_token:
        data.update({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
    else:
        raise RuntimeError("Provide either code or refresh_token")
    r = s.post(TOKEN_URL, data=data, timeout=45)
    js = r.json()
    if js.get("status") != 0:
        raise RuntimeError(f"Withings token request failed: {js}")
    return js["body"]


def fetch_measures(s: requests.Session, access_token: str, start_ts: int, end_ts: int) -> dict:
    """Fetch measures for the given Unix timestamp window."""
    params = {
        "action": "getmeas",
        "meastypes": "1,6,76,77",  # weight, fat ratio, muscle mass, hydration
        "category": 1,
        "startdate": start_ts,
        "enddate": end_ts,
    }
    r = s.get(
        MEASURE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
        timeout=45,
    )
    return r.json()


def london_prev_day() -> tuple[int, int, str]:
    """Return (start_ts, end_ts, iso_date) for yesterday in Europe/London."""
    london = ZoneInfo("Europe/London")
    now_ldn = datetime.now(london)
    prev_date = now_ldn.date() - timedelta(days=1)
    start_ldn = datetime(prev_date.year, prev_date.month, prev_date.day, tzinfo=london)
    end_ldn = start_ldn + timedelta(days=1) - timedelta(seconds=1)
    return (
        int(start_ldn.astimezone(timezone.utc).timestamp()),
        int(end_ldn.astimezone(timezone.utc).timestamp()),
        prev_date.isoformat(),
    )


def main() -> None:
    if not (CLIENT_ID and CLIENT_SECRET and REDIRECT_URI):
        print("Missing WITHINGS_CLIENT_ID/SECRET/REDIRECT_URI", file=sys.stderr)
        sys.exit(2)
    s = session_with_retries()
    # Support local first-run via --code
    code_arg = None
    if len(sys.argv) > 1 and sys.argv[1].startswith("--code="):
        code_arg = sys.argv[1].split("=", 1)[1]

    if code_arg and not REFRESH_TOKEN:
        body = token_exchange(s, code=code_arg)
        access = body["access_token"]
    else:
        if not REFRESH_TOKEN:
            print("WITHINGS_REFRESH_TOKEN not set; run locally with --code=<...> first.", file=sys.stderr)
            sys.exit(2)
        body = token_exchange(s, refresh_token=REFRESH_TOKEN)
        access = body["access_token"]

    start_ts, end_ts, date_str = london_prev_day()
    measures = fetch_measures(s, access, start_ts, end_ts)

    # Build summarised row for the day
    row = {
        "date": date_str,
        "weight_kg": None,
        "body_fat_pct": None,
        "muscle_mass_kg": None,
        "water_pct": None,
        "source": "withings",
        "is_partial_weight": True,
    }
    if measures.get("status") == 0:
        for grp in (measures.get("body", {}) or {}).get("measuregrps", []):
            # Use the last measure group of the day
            dt = datetime.fromtimestamp(grp.get("date", 0), tz=timezone.utc).astimezone(ZoneInfo("Europe/London"))
            if dt.date().isoformat() != date_str:
                continue
            def val(type_id: int) -> Optional[float]:
                for m in grp.get("measures", []):
                    if m.get("type") == type_id:
                        return m["value"] * (10 ** m.get("unit", 0))
                return None
            w  = val(1)
            bf = val(6)
            mm = val(76)
            wp = val(77)
            row["weight_kg"]      = round(w, 2) if w is not None else None
            row["body_fat_pct"]   = round(bf, 2) if bf is not None else None
            row["muscle_mass_kg"] = round(mm, 2) if mm is not None else None
            row["water_pct"]      = round(wp, 2) if wp is not None else None
            row["is_partial_weight"] = False if w is not None else True

    # Write per-day, daily, and update history
    write_json(DAYS_DIR / f"{date_str}.json", row)
    write_json(DAILY_PATH, row)
    # Update rolling history (max 90 entries)
    history = []
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text())
        except Exception:
            history = []
    history = [h for h in history if h.get("date") != date_str]
    history.append(row)
    history.sort(key=lambda x: x.get("date", ""), reverse=True)
    history = history[:90]
    write_json(HISTORY_PATH, history)
    print(json.dumps({"prev_day": date_str, "updated": [str(DAYS_DIR / f"{date_str}.json"), str(DAILY_PATH), str(HISTORY_PATH)]}, indent=2))


if __name__ == "__main__":
    main()
