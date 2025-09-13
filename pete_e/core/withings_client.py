"""
Withings API client for Pete-E
Refactored from a procedural script to a class-based client.
It uses a centralized configuration service for credentials.
"""

import requests
from datetime import datetime, timedelta, timezone

# Import the centralized settings object
from pete_e.config import settings
from pete_e.infra.log_utils import log_message


class WithingsClient:
    """A client to interact with the Withings API."""

    def __init__(self):
        """Initializes the client with credentials from the settings."""
        self.client_id = settings.WITHINGS_CLIENT_ID
        self.client_secret = settings.WITHINGS_CLIENT_SECRET
        self.redirect_uri = settings.WITHINGS_REDIRECT_URI
        self.refresh_token = settings.WITHINGS_REFRESH_TOKEN
        self.access_token = None
        self.token_url = "https://wbsapi.withings.net/v2/oauth2"
        self.measure_url = "https://wbsapi.withings.net/measure"

    def _refresh_access_token(self):
        """Exchanges the refresh token for a new access token."""
        log_message("Refreshing Withings access token.")
        data = {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }
        r = requests.post(self.token_url, data=data, timeout=30)
        r.raise_for_status()
        js = r.json()
        if js.get("status") != 0:
            raise RuntimeError(f"Withings token refresh failed: {js}")
        
        self.access_token = js["body"]["access_token"]
        log_message("Successfully refreshed Withings access token.")

    def _fetch_measures(self, start: datetime, end: datetime) -> dict:
        """Fetches Withings measures for a given time window."""
        if not self.access_token:
            self._refresh_access_token()
            
        params = {
            "action": "getmeas",
            "meastypes": "1,6,76,77",  # weight, fat %, muscle, water
            "category": 1,
            "startdate": int(start.timestamp()),
            "enddate": int(end.timestamp()),
        }
        r = requests.get(
            self.measure_url,
            headers={"Authorization": f"Bearer {self.access_token}"},
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def get_summary(self, days_back: int = 1) -> dict:
        """
        Returns a summary dict for a given day.
        Includes: weight, fat %, muscle mass, and water %.
        """
        tz = timezone.utc
        today = datetime.now(tz).date()
        target_date = today - timedelta(days=days_back)
        start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)
        end = start + timedelta(days=1)

        js = self._fetch_measures(start, end)
        if js.get("status") != 0:
            raise RuntimeError(f"Withings fetch failed: {js}")

        measures = js.get("body", {}).get("measuregrps", [])
        if not measures:
            log_message(f"No Withings measures found for {target_date.isoformat()}.")
            return {"date": target_date.isoformat()}

        latest = measures[-1]
        row = {"date": target_date.isoformat()}

        def val(type_id: int):
            for m in latest.get("measures", []):
                if m.get("type") == type_id:
                    return m["value"] * (10 ** m.get("unit", 0))
            return None

        row["weight"] = round(val(1), 2) if val(1) is not None else None
        row["fat_percent"] = round(val(6), 2) if val(6) is not None else None
        row["muscle_mass"] = round(val(76), 2) if val(76) is not None else None
        row["water_percent"] = round(val(77), 2) if val(77) is not None else None

        log_message(f"Successfully fetched Withings summary for {target_date.isoformat()}.")
        return row
