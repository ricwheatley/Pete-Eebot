# (Functional) Workout exporter (v3) – updated version for exporting training week data to Wger.
# (Used by weekly reviewer for auto-export.)

from __future__ import annotations

import os
import datetime as dt
from typing import Any, Dict, List, Optional
from pete_e.infrastructure.plan_rw import log_wger_export

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
            raise WgerError(f"POST {path} failed with {r.status_code}", r)
        return r.json()

    # --- high-level helpers ----

    # Routines
    def find_routine(self, *, name: str, start: dt.date) -> Optional[Dict[str, Any]]:
        data = self.get("/api/v2/routine/", params={"name": name, "start": start.isoformat()})
        results = data.get("results", [])
        return results[0] if results else None

    def create_routine(self, *, name: str, description: Optional[str], start: dt.date, end: dt.date) -> Dict[str, Any]:
        payload = {
            "name": name,
            "description": description or "Created by Pete-Eebot",
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        return self.post("/api/v2/routine/", payload)

    # Weeks
    def create_week(self, *, routine_id: int, order: int) -> Dict[str, Any]:
        payload = {
            "routine": routine_id,
            "order": order,
        }
        return self.post("/api/v2/workoutsessionweek/", payload)

    # Days
    def find_day(self, *, routine_id: int, order: int) -> Optional[Dict[str, Any]]:
        data = self.get("/api/v2/day/", params={"routine": routine_id, "order": order})
        results = data.get("results", [])
        return results[0] if results else None

    def create_day(
        self, *, routine_id: int, order: int, name: Optional[str] = None,
        is_rest: bool = False, week_id: Optional[int] = None
    ) -> Dict[str, Any]:
        payload = {
            "routine": routine_id,
            "order": order,
            "name": name or "",
            "is_rest": is_rest,
        }
        if week_id is not None:
            payload["week"] = week_id
        return self.post("/api/v2/day/", payload)

    # Slots
    def create_slot(self, *, day_id: int, order: int, comment: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "day": day_id,
            "order": order,
            "comment": (comment or "")[:200],
        }
        return self.post("/api/v2/slot/", payload)

    # Slot Entries
    def create_slot_entry(
        self, *, slot_id: int, exercise_id: int,
        order: int, comment: Optional[str] = None,
        repetition_unit_id: Optional[int] = None,
        weight_unit_id: Optional[int] = None
    ) -> Dict[str, Any]:
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
        return self.post("/api/v2/slot-entry/", payload)

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
        return self.post("/api/v2/sets-config/", payload)

    def set_reps(self, slot_entry_id: int, reps: int) -> Dict[str, Any]:
        payload = {
            "slot_entry": slot_entry_id,
            "iteration": 1,
            "value": str(int(reps)),  # API expects decimal string
            "operation": "r",
            "step": "na",
            "repeat": True,
        }
        return self.post("/api/v2/repetitions-config/", payload)

    def set_rir(self, slot_entry_id: int, rir_value: float) -> Dict[str, Any]:
        payload = {
            "slot_entry": slot_entry_id,
            "iteration": 1,
            "value": f"{rir_value:.1f}",
            "operation": "r",
            "step": "na",
            "repeat": True,
        }
        return self.post("/api/v2/rir-config/", payload)

    # Look up units
    def repetition_unit_id(self, name: str = "repetitions") -> Optional[int]:
        data = self.get("/api/v2/setting-repetitionunit/", params={"name": name})
        results = data.get("results", [])
        return results[0]["id"] if results else None

    def weight_unit_id(self, name: str = "kg") -> Optional[int]:
        data = self.get("/api/v2/setting-weightunit/", params={"name": name})
        results = data.get("results", [])
        return results[0]["id"] if results else None


def routine_name_for_date(start: dt.date) -> str:
    return f"Wk {start.day} {start.strftime('%B')} {start.strftime('%y')}"


def weekday_name(day_of_week: int) -> str:
    names = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
    return names.get(day_of_week, f"Day {day_of_week}")


def export_week_to_wger(
    week_payload: Dict[str, Any],
    week_start: dt.date,
    week_end: Optional[dt.date] = None,
    *,
    routine_name: Optional[str] = None,
    routine_desc: Optional[str] = None,
    blaze_exercise_id: int = 1630
) -> Dict[str, Any]:
    client = WgerClient()
    rep_unit_id = client.repetition_unit_id()

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

    # 2) Create a week in Wger
    week_number = int(week_payload.get("week_number", 1))
    week = client.create_week(routine_id=routine_id, order=week_number)
    week_id = week["id"]

    # 3) Days and slots
    ordered_days = sorted(week_payload.get("days", []), key=lambda d: int(d.get("day_of_week", 0)))
    day_order = 1
    for day in ordered_days:
        dow = int(day.get("day_of_week"))
        exercises: List[Dict[str, Any]] = day.get("exercises", [])

        day_name = weekday_name(dow)
        wger_day = client.create_day(routine_id=routine_id, order=day_order, name=day_name, week_id=week_id)
        day_id = wger_day["id"]
        created_day = {"order": day_order, "source_day_of_week": dow, "id": day_id, "slots": []}

        slot_order = 1
        for ex in exercises:
            ex_id = int(ex.get("exercise"))
            sets = int(ex.get("sets", 0) or 0)
            reps = int(ex.get("reps", 0) or 0)
            comment = ex.get("comment") or ""

            if ex_id == blaze_exercise_id:
                slot = client.create_slot(day_id=day_id, order=slot_order, comment=comment or "Blaze class")
                created_day["slots"].append({"slot_id": slot["id"], "type": "comment-only"})
                slot_order += 1
                continue

            slot = client.create_slot(day_id=day_id, order=slot_order)
            slot_id = slot["id"]

            slot_entry = client.create_slot_entry(
                slot_id=slot_id,
                exercise_id=ex_id,
                order=1,
                comment=comment[:100],
                repetition_unit_id=rep_unit_id,
                weight_unit_id=None,
            )
            slot_entry_id = slot_entry["id"]

            if sets > 0:
                client.set_sets(slot_entry_id, sets)
            if reps > 0:
                client.set_reps(slot_entry_id, reps)

            # crude RIR extraction from comment
            rir_val: Optional[float] = None
            lower = comment.lower()
            if "rir" in lower:
                import re
                m = re.search(r"([0-9]+(?:\.[0-9])?)", lower.split("rir", 1)[1])
                if m:
                    try:
                        rir_val = float(m.group(1))
                    except Exception:
                        rir_val = None
            if rir_val is not None:
                client.set_rir(slot_entry_id, rir_val)

            created_day["slots"].append(
                {"slot_id": slot_id, "slot_entry_id": slot_entry_id, "exercise": ex_id}
            )
            slot_order += 1

        created["days"].append(created_day)
        day_order += 1

    # 4) Log the export
    plan_id = week_payload.get("plan_id")
    if plan_id:
        try:
            log_wger_export(plan_id, week_number, week_payload, routine, routine_id=routine_id)
        except Exception as e:
            import sys
            print(f"[warn] failed to log wger export: {e}", file=sys.stderr)

    return created
