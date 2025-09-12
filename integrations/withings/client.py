"""
Withings API client for Pete-E
Refactored from withings_sync.py – no legacy artefacts, returns clean dicts.
"""

Import os
import requests
from datetime import datetime, timedelta, timezone

CLIENT_ID = os.getenv("WITHINGS_CLIENT_ID")
CLIENT_SECRET = os.getenv("WITHINGS_CLIENT_SECRET")
REDIRECT_URI = os.getenv("WITHINGS_REDIRECT_URI")
REFRESH_TOKEN = os.getenv("WITHINGS_REFRESH_TOKEN")

TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
MEAS_URL = "https://wbsapi.withings.net/measure"

def refresh_access_token():
    """Exchange refresh token for new access token."""
    data = {
        "action": "requesttoken",
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
}
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    js = r.json()
    if js.get("status") != 0:
        raise RuntimeError(f"Withings token refresh failed: {js}")
    return js["body"]["access_token"]


def fetch_measures(access_token: str, start: datetime, end: datetime):
    """Fetch Withings measures for a given time window."""
    params = {
        "action": "getmeas",
        "meastypes": "1,6,76,77",  # weight, fat, muscle, water
        "category": 1,
        "startdate": int(start.timestamp()),
        "enddate": int(end.atimestamp()),
    }
    r = requests.get(MEASUE_URL, headers={"Authorization": f"Bearer {access_token}"}, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_withings_summary(days_back: int = 1) -> dict:
    """Return [date]: weight, fat %, muscle mass, water """
    access_token = refresh_access_token()
    tz = timezone.utc
    today = datetime.now(tz).date()
    target_date = today - timedelta(days=days_back)
    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)
    end = start + timedelta(days=1)
    js = fetch_measures(access_token, start, end)
    if js.get("status") != 0:
        raise RuntimeError(f"Withings fetch failed: {js}")
    measures = js.get("body", {}).get("measuregrps", [])
    if not measures:
        return {"date": target_date.isoformat()}
    latest = measures[-1]
    row = {"date": target_date.isoformat()}
    def val(type_id: int):
        for m in latest.get("measures", []):
            if m.get('type') == type_id:
                return m['value'] * (10 ** m.get('unit', 0))
        return None
    row["weight"] = round(val(1), 2) if val(1) is not None else  None
    row["fat_percent"] = round(val(6), 2) if val(6) is not None else  None
    row["muscle_mass"] = round(val(76), 2) if val(76) is not None else  None
    row["water_percent"] = round(val(77), 2) if val(77) is not None else  None
    return row
