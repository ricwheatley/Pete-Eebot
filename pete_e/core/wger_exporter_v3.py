# pete_e/integrations/wger/exporter_v3.py
from __future__ import annotations

import os
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple
from pete_e.data_access.plan_rw import log_wger_export

import requests


class WgerError(RuntimeError):
    def __init__(self, msg: str, resp: Optional[requests.Response] = None):
        super().__init__(msg)
        self.resp = resp
        self.status_code = None if resp is None else resp.status_code
        self.text = None if resp is None else resp.text


class WgerClient:
    """
    Thin HTTP client around the wger API v2.

    Auth: Authorization: Token <KEY>  - token-based auth with 'Token' prefix. 
    """
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None, timeout: int = 30):
        self.base_url = (base_url or os.getenv("WGER_API_BASE") or "https://wger.de").rstrip("/")
        self.token = token or os.getenv("WGER_API_KEY")
        if not self.token:
            raise WgerError("WGER_API_KEY is not set in environment")
        self.timeout = timeout

    # --- low-level ----
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Token {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        # paths in the OpenAPI spec include trailing slash, keep it to avoid 301/404
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = requests.get(self._url(path), headers=self._headers(), params=params, timeout=self.timeout)
        if r.status_code != 200:
            raise WgerError(f"GET {path} failed with {r.status_code}", r)
        return r.json()

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.post(self._url(path), headers=self._headers(), json=payload, timeout=self.timeout)
        if r.status_code not in (200, 201):
            # wger returns HTML error pages for some errors, include text for diagnostics
            raise WgerError(f"POST {path} failed with {r.status_code}", r)
        return r.json()

    # --- high-level helpers ----

    # Routines
    def find_routine(self, *, name: str, start: dt.date) -> Optional[Dict[str, Any]]:
        # Supports name and start filters. 
        data = self.get("/api/v2/routine/", params={"name": name, "start": start.isoformat()})
        results = data.get("results", [])
        return results[0] if results else None  # :contentReference[oaicite:6]{index=6}

    def create_routine(self, *, name: str, description: Optional[str], start: dt.date, end: dt.date) -> Dict[str, Any]:
        payload = {
            "name": name,
            "description": description or "Created by Pete-Eebot",
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        return self.post("/api/v2/routine/", payload)


    # Days
    def find_day(self, *, routine_id: int, order: int) -> Optional[Dict[str, Any]]:
        data = self.get("/api/v2/day/", params={"routine": routine_id, "order": order})
        results = data.get("results", [])
        return results[0] if results else None  # :contentReference[oaicite:8]{index=8}

    def create_day(self, *, routine_id: int, order: int, name: Optional[str] = None,
                   is_rest: bool = False) -> Dict[str, Any]:
        payload = {
            "routine": routine_id,
            "order": order,
            "name": name or "",
            "is_rest": is_rest,
        }
        return self.post("/api/v2/day/", payload)  # :contentReference[oaicite:9]{index=9}

    # Slots
    def create_slot(self, *, day_id: int, order: int, comment: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "day": day_id,
            "order": order,
            "comment": (comment or "")[:200],
        }
        return self.post("/api/v2/slot/", payload)  # :contentReference[oaicite:10]{index=10}

    # Slot Entries
    def create_slot_entry(self, *, slot_id: int, exercise_id: int,
                          order: int, comment: Optional[str] = None,
                          repetition_unit_id: Optional[int] = None,
                          weight_unit_id: Optional[int] = None) -> Dict[str, Any]:
        payload = {
            "slot": slot_id,
            "exercise": exercise_id,
            "order": order,
            "comment": (comment or "")[:100],
        }
        if repetition_unit_id is not None:
            payload["repetition_unit"] = repetition_unit_id
        if weight_unit_id is not None:
            payload["weight_unit"] = weight_unit_id
        return self.post("/api/v2/slot-entry/", payload)  # :contentReference[oaicite:11]{index=11}

    # Configs for set count, reps and RiR
    def set_sets(self, slot_entry_id: int, sets: int) -> Dict[str, Any]:
        payload = {
            "slot_entry": slot_entry_id,
            "iteration": 1,
            "value": int(sets),
            "operation": "r",
            "step": "na",
            "repeat": True,
        }
        return self.post("/api/v2/sets-config/", payload)  # :contentReference[oaicite:12]{index=12}

    def set_reps(self, slot_entry_id: int, reps: int) -> Dict[str, Any]:
        payload = {
            "slot_entry": slot_entry_id,
            "iteration": 1,
            "value": str(int(reps)),  # API expects decimal string
            "operation": "r",
            "step": "na",
            "repeat": True,
        }
        return self.post("/api/v2/repetitions-config/", payload)  # :contentReference[oaicite:13]{index=13}

    def set_rir(self, slot_entry_id: int, rir_value: float) -> Dict[str, Any]:
        payload = {
            "slot_entry": slot_entry_id,
            "iteration": 1,
            "value": f"{rir_value:.1f}",  # decimal string, 1 dp
            "operation": "r",
            "step": "na",
            "repeat": True,
        }
        return self.post("/api/v2/rir-config/", payload)  # 

    # Look up units, optional quality of life
    def repetition_unit_id(self, name: str = "repetitions") -> Optional[int]:
        data = self.get("/api/v2/setting-repetitionunit/", params={"name": name})  # :contentReference[oaicite:15]{index=15}
        results = data.get("results", [])
        return results[0]["id"] if results else None

    def weight_unit_id(self, name: str = "kg") -> Optional[int]:
        data = self.get("/api/v2/setting-weightunit/", params={"name": name})  # :contentReference[oaicite:16]{index=16}
        results = data.get("results", [])
        return results[0]["id"] if results else None
    
def routine_name_for_date(start: dt.date) -> str:
    """
    Generate a short routine name like 'Wk 22 September 25'.
    Always <= 25 characters to satisfy Wger API.
    """
    return f"Wk {start.day} {start.strftime('%B')} {start.strftime('%y')}"



def weekday_name(day_of_week: int) -> str:
    # Map 1..7 like your payload uses, 1 = Monday
    names = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
    return names.get(day_of_week, f"Day {day_of_week}")


def export_week_to_wger(week_payload: Dict[str, Any],
                        week_start: dt.date,
                        week_end: Optional[dt.date] = None,
                        *,
                        routine_name: Optional[str] = None,
                        routine_desc: Optional[str] = None,
                        blaze_exercise_id: int = 99999) -> Dict[str, Any]:
    """
    Create or update a wger routine for a given week and push all slots + entries.

    week_payload shape must be like the object your generator prints:
    {
      "days": [
         {"day_of_week": 1, "exercises": [
             {"exercise": 73, "sets": 4, "reps": 8, "comment": "..."},
             ...
         ]},
         ...
      ]
    }
    """
    client = WgerClient()
    rep_unit_id = client.repetition_unit_id()  # optional, if None, wger still accepts the slot entry
    # weight_unit_id = client.weight_unit_id("kg")  # we do not set weight configs yet

    week_end = week_end or (week_start + dt.timedelta(days=6))
    routine_name = routine_name or routine_name_for_date(week_start)
    routine_desc = routine_desc or "Auto-scheduled by Pete-Eebot"

    # 1) Routine
    existing = client.find_routine(name=routine_name, start=week_start)
    if existing:
        routine = existing
    else:
        routine = client.create_routine(name=routine_name, description=routine_desc, start=week_start, end=week_end)

    routine_id = routine["id"]

    created: Dict[str, Any] = {"routine_id": routine_id, "days": []}

    # 2) Days and slots
    # We keep the order stable and compact, independent of actual weekday numbers,
    # but set the name to the weekday for readability in wger.
    ordered_days = sorted(week_payload.get("days", []), key=lambda d: int(d.get("day_of_week", 0)))
    day_order = 1
    for day in ordered_days:
        dow = int(day.get("day_of_week"))
        exercises: List[Dict[str, Any]] = day.get("exercises", [])

        # If a day only contains Blaze, we still create a day with one comment slot.
        day_name = weekday_name(dow)
        wger_day = client.find_day(routine_id=routine_id, order=day_order) or \
                   client.create_day(routine_id=routine_id, order=day_order, name=day_name)
        day_id = wger_day["id"]
        created_day = {"order": day_order, "source_day_of_week": dow, "id": day_id, "slots": []}

        slot_order = 1
        for ex in exercises:
            ex_id = int(ex.get("exercise"))
            sets = int(ex.get("sets", 0) or 0)
            reps = int(ex.get("reps", 0) or 0)
            comment = ex.get("comment") or ""

            if ex_id == blaze_exercise_id:
                # Blaze - create a plain slot with a comment
                slot = client.create_slot(day_id=day_id, order=slot_order, comment=comment or "Blaze class")
                created_day["slots"].append({"slot_id": slot["id"], "type": "comment-only"})
                slot_order += 1
                continue

            # Normal lifting movement
            slot = client.create_slot(day_id=day_id, order=slot_order)
            slot_id = slot["id"]

            # Blend a short human comment that will show up in the app UI
            short_comment = comment
            slot_entry = client.create_slot_entry(
                slot_id=slot_id,
                exercise_id=ex_id,
                order=1,
                comment=short_comment[:100],
                repetition_unit_id=rep_unit_id,
                weight_unit_id=None,
            )
            slot_entry_id = slot_entry["id"]

            # Targets - sets, reps, rir
            if sets > 0:
                client.set_sets(slot_entry_id, sets)
            if reps > 0:
                client.set_reps(slot_entry_id, reps)

            # extract 'RIR 2.0' if present in comment
            rir_val: Optional[float] = None
            lower = comment.lower()
            if "rir" in lower:
                try:
                    after = lower.split("rir", 1)[1]
                    # find first float-ish token
                    import re
                    m = re.search(r"([0-9]+(?:\.[0-9])?)", after)
                    if m:
                        rir_val = float(m.group(1))
                except Exception:
                    rir_val = None
            if rir_val is not None:
                client.set_rir(slot_entry_id, rir_val)

            created_day["slots"].append({"slot_id": slot_id, "slot_entry_id": slot_entry_id, "exercise": ex_id})
            slot_order += 1

        created["days"].append(created_day)
        day_order += 1

        plan_id = week_payload.get("plan_id")
        week_number = week_payload.get("week_number")
        if plan_id and week_number:
            try:
                log_wger_export(plan_id, int(week_number), week_payload, routine, routine_id=routine_id)
            except Exception as e:
                # don’t blow up on logging errors, just emit to stderr
                import sys
                print(f"[warn] failed to log wger export: {e}", file=sys.stderr)

        return created
