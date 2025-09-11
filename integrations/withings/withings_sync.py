#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Withings sync, JSON-only – no raw snapshots.

Outputs:
  docs/withings/days/<YYYY-MM-DD>.json
  docs/withings/daily.json
  docs/withings/history.json  (rolling last 90 days)

Set env vars:
  WITHINGS_CLIENT_ID, WITHINGS_CLIENT_SECRET,
  WITHINGS_REDIRECT_URI, WITHINGS_REFRESH_TOKEN,
  WITHINGS_DAYS_BACK (optional, default 14)
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

# Endpoints and config
TOKEN_URL   = "https://wbsapi.withings.net/v2/oauth2"
MEASURE_URL = "https://wbsapi.withings.net/measure"

CLIENT_ID     = os.getenv("WITHINGS_CLIENT_ID")
CLIENT_SECRET = os.getenv("WITHINGS_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("WITHINGS_REDIRECT_URI")
REFRESH_TOKEN = os.getenv("WITHINGS_REFRESH_TOKEN")
DAYS_BACK     = int(os.getenv("WITHINGS_DAYS_BACK", "14"))

# Output paths
BASE      = Path("docs/withings")
DAYS_DIR  = BASE / "days"
DAILY_P   = BASE / "daily.json"
HISTORY_P = BASE / "history.json"
DAYS_DIR.mkdir(parents=True, exist_ok=True)

def session_with_retries(total=5, backoff=0.6) -> requests.Session:
    s = requests.Session()
    retry = requests.packages.urllib3.util.retry.Retry(
        total=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET","POST"]),
        raise_on_status=False,
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

def write_json(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

def token_exchange(s: requests.Session, *, code: Optional[str]=None, refresh_token: Optional[str]=None) -> dict:
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

def fetch_measures(s: requests.Session, access: str, start_ts: int, end_ts: int) -> dict:
    params = {
        "action": "getmeas",
        "meastypes": "1,6,76,77",
        "category": 1,
        "startdate": start_ts,
        "enddate": end_ts,
    }
    r = s.get(MEASURE_URL, headers={"Authorization": f"Bearer {access}"}, params=params, timeout=45)
    return r.json()

def london_prev_day() -> tuple[int,int,str]:
    london = ZoneInfo("Europe/London")
    now_ldn = datetime.now(london)
    prev_date = now_ldn.date() - timedelta(days=1)
    start_ldn = datetime(prev_date.year, prev_date.month, prev_date.day, tzinfo=london)
    end_ldn   = start_ldn + timedelta(days=1) - timedelta(seconds=1)
    return (
        int(start_ldn.astimezone(timezone.utc).timestamp()),
        int(end_ldn.astimezone(timezone.utc).timestamp()),
        prev_date.isoformat(),
    )

def main():
    if not (CLIENT_ID and CLIENT_SECRET and REDIRECT_URI):
        print("Missing WITHINGS_CLIENT_ID/SECRET/REDIRECT_URI", file=sys.stderr)
        sys.exit(2)
    s = session_with_retries()
    code = None
    if len(sys.argv) > 1 and sys.argv[1].startswith("--code="):
        code = sys.argv[1].split("=",1)[1]

    if code and not REFRESH_TOKEN:
        body = token_exchange(s, code=code)
        access = body["access_token"]
    else:
        if not REFRESH_TOKEN:
            print("WITHINGS_REFRESH_TOKEN not set; run locally with --code=<...> first.", file=sys.stderr)
            sys.exit(2)
        body = token_exchange(s, refresh_token=REFRESH_TOKEN)
        access = body["access_token"]

    start_ts, end_ts, date_str = london_prev_day()
    measures = fetch_measures(s, access, start_ts, end_ts)

    # summarise body composition for that day
    row = {"date": date_str, "weight_kg": None, "body_fat_pct": None,
           "muscle_mass_kg": None, "water_pct": None, "source":"withings", "is_partial_weight": True}
    if measures.get("status") == 0:
        for grp in (measures.get("body",{}) or {}).get("measuregrps", []):
            # keep the last entry of the day
            dt = datetime.fromtimestamp(grp.get("date",0), tz=timezone.utc).astimezone(ZoneInfo("Europe/London"))
            if dt.date().isoformat() != date_str:
                continue
            def val(type_id: int):
                for m in grp.get("measures", []):
                    if m.get("type") == type_id:
                        return m["value"] * (10 ** m.get("unit", 0))
                return None
            row["weight_kg"]      = round(val(1),2) if val(1) is not None else None
            row["body_fat_pct"]   = round(val(6),2) if val(6) is not None else None
            row["muscle_mass_kg"] = round(val(76),2) if val(76) is not None else None
            row["water_pct"]      = round(val(77),2) if val(77) is not None else None
            row["is_partial_weight"] = False if row["weight_kg"] is not None else True

    write_json(DAYS_DIR / f"{date_str}.json", row)
    write_json(DAILY_P, row)
    # update history (rolling 90 days)
    history = []
    if HISTORY_P.exists():
        try: history = json.loads(HISTORY_P.read_text())
        except Exception: history = []
    history = [h for h in history if h.get("date") != date_str]
    history.append(row)
    history.sort(key=lambda x: x.get("date",""), reverse=True)
    history = history[:90]
    write_json(HISTORY_P, history)
    print(json.dumps({"prev_day": date_str, "updated": ["days", "daily", "history"]}))

if __name__ == "__main__":
    main()
