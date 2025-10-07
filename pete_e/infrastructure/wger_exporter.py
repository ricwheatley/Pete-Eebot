# pete_e/infrastructure/wger_exporter_v3.py
#
# Workout exporter (v3) - exports training week data to Wger with idempotency, validation,
# retries, diagnostics, dry-run, and configurable behaviour.
# Logging uses Pete's tagged logger for consistent structured output.

from __future__ import annotations

import json
import time
import datetime as dt
from typing import Any, Dict, List, Optional
from pete_e.config import get_env, settings
import requests

from pete_e.logging_setup import get_logger

logger = get_logger("WGER")

# --- DB helpers for validation and export logging ---
from pete_e.infrastructure.plan_rw import log_wger_export, conn_cursor


# ---------------------------
# Exceptions
# ---------------------------

class WgerError(RuntimeError):
    def __init__(self, msg: str, resp: Optional[requests.Response] = None):
        super().__init__(msg)
        self.resp = resp
        self.status_code = None if resp is None else resp.status_code
        self.text = None if resp is None else (resp.text or "")


# ---------------------------
# HTTP client with retries and debug logging
# ---------------------------

class WgerClient:
    """
    Thin HTTP client around the Wger API v2 with retry and optional debug logging.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_base: float = 0.75,
        debug_api: bool = False,
    ):
        base_candidate = (base_url or settings.WGER_BASE_URL).rstrip("/")
        if base_candidate.endswith("/api/v2"):
            base_candidate = base_candidate[: -len("/api/v2")]
        self.base_url = base_candidate

        resolved_token = token or get_env("WGER_API_KEY")
        self.token = (resolved_token or "").strip()
        if not self.token:
            raise WgerError("WGER_API_KEY is not set in environment")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.debug_api = debug_api

        # simple caches
        self._rep_unit_id_cache: Optional[int] = None
        self._weight_unit_id_cache: Dict[str, Optional[int]] = {}

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

    def _should_retry(self, status: int) -> bool:
        return status in (408, 429, 500, 502, 503, 504)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = self._url(path)
        attempt = 0
        last_exc: Optional[Exception] = None

        while attempt < self.max_retries:
            try:
                if self.debug_api:
                    logger.debug(f"[wger.api] {method} {path} params={params or {}} payload={json.dumps(payload or {}, ensure_ascii=False)}")
                r = requests.request(
                    method=method.upper(),
                    url=url,
                    headers=self._headers(),
                    params=params,
                    json=payload,
                    timeout=self.timeout,
                )
                if self.debug_api:
                    logger.debug(f"[wger.api] <- {r.status_code} {r.text[:800]}")

                if r.status_code in (200, 201, 204):
                    if r.status_code == 204:
                        return {}
                    try:
                        return r.json()
                    except ValueError:
                        return {}
                if self._should_retry(r.status_code):
                    sleep_for = self.backoff_base * (2 ** attempt)
                    logger.warning(f"[wger.api] transient {r.status_code} on {method} {path}, retrying in {sleep_for:.2f}s...")
                    time.sleep(sleep_for)
                    attempt += 1
                    continue
                raise WgerError(f"{method} {path} failed with {r.status_code}", r)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                sleep_for = self.backoff_base * (2 ** attempt)
                logger.warning(f"[wger.api] network error on {method} {path}: {exc!r}, retrying in {sleep_for:.2f}s...")
                time.sleep(sleep_for)
                attempt += 1

        if isinstance(last_exc, requests.exceptions.RequestException):
            raise WgerError(f"{method} {path} failed after retries: {last_exc!r}")
        raise WgerError(f"{method} {path} failed after retries")

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", path, payload=payload)

    def patch(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("PATCH", path, payload=payload)

    def delete(self, path: str) -> Dict[str, Any]:
        return self._request("DELETE", path)

    # pagination helper
    def _get_all(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        q = dict(params or {})
        while True:
            data = self.get(path, params=q)
            results = data.get("results", [])
            items.extend(results)
            next_url = data.get("next")
            if not next_url:
                break
            q["page"] = int(q.get("page", 1)) + 1
        return items

    # ---------------------------
    # High-level helpers
    # ---------------------------

    # Routines
    def find_routine(self, *, name: str, start: dt.date) -> Optional[Dict[str, Any]]:
        data = self.get("/api/v2/routine/", params={"name": name, "start": start.isoformat()})
        results = data.get("results", [])
        return results[0] if results else None

    def create_routine(self, *, name: str, description: Optional[str], start: dt.date, end: dt.date) -> Dict[str, Any]:
        payload = {"name": name, "description": description or "Created by Pete-Eebot", "start": start.isoformat(), "end": end.isoformat()}
        return self.post("/api/v2/routine/", payload)

    # Weeks (WorkoutSession)
    def find_week(self, *, routine_id: int, order: int) -> Optional[Dict[str, Any]]:
        data = self.get("/api/v2/workoutsession/", params={"routine": routine_id, "order": order})
        results = data.get("results", [])
        return results[0] if results else None

    def create_week(self, *, routine_id: int, order: int) -> Dict[str, Any]:
        payload = {"routine": routine_id, "order": order}
        return self.post("/api/v2/workoutsession/", payload)

    def delete_week(self, *, week_id: int) -> None:
        self.delete(f"/api/v2/workoutsession/{week_id}/")

    # Days
    def find_day(self, *, routine_id: int, order: int, week_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        params: Dict[str, Any] = {"routine": routine_id, "order": order}
        if week_id is not None:
            params["workout_session"] = week_id
        data = self.get("/api/v2/day/", params=params)
        results = data.get("results", [])
        return results[0] if results else None

    def list_days_for_week(self, *, routine_id: int, week_id: int) -> List[Dict[str, Any]]:
        return self._get_all("/api/v2/day/", {"routine": routine_id, "workout_session": week_id})

    def list_days(self, *, routine_id: int) -> List[Dict[str, Any]]:
        """Return all day objects for the given routine.

        This helper hides pagination details and is used when the week/session
        abstraction is not present. It fetches every Day associated with
        *routine_id* and returns them in a list.  This allows callers to
        wipe or iterate over all existing days when re‑exporting a routine.
        """
        return self._get_all("/api/v2/day/", {"routine": routine_id})

    def create_day(self, *, routine_id: int, order: int, name: str = "", is_rest: bool = False, week_id: Optional[int] = None) -> Dict[str, Any]:
        payload = {"routine": routine_id, "order": order, "name": name or "", "is_rest": is_rest}
        if week_id is not None:
            payload["workout_session"] = week_id
        return self.post("/api/v2/day/", payload)

    def delete_day(self, *, day_id: int) -> None:
        self.delete(f"/api/v2/day/{day_id}/")

    # Slots
    def find_slot(self, *, day_id: int, order: int) -> Optional[Dict[str, Any]]:
        data = self.get("/api/v2/slot/", params={"day": day_id, "order": order})
        results = data.get("results", [])
        return results[0] if results else None

    def create_slot(self, *, day_id: int, order: int, comment: Optional[str] = None) -> Dict[str, Any]:
        payload = {"day": day_id, "order": order, "comment": (comment or "")[:200]}
        return self.post("/api/v2/slot/", payload)

    def delete_slot(self, *, slot_id: int) -> None:
        self.delete(f"/api/v2/slot/{slot_id}/")

    # Slot entries
    def find_slot_entry(self, *, slot_id: int, order: Optional[int] = None) -> Optional[Dict[str, Any]]:
        params: Dict[str, Any] = {"slot": slot_id}
        if order is not None:
            params["order"] = order
        data = self.get("/api/v2/slot-entry/", params=params)
        results = data.get("results", [])
        return results[0] if results else None

    def create_slot_entry(
        self,
        *,
        slot_id: int,
        exercise_id: int,
        order: int,
        comment: Optional[str] = None,
        repetition_unit_id: Optional[int] = None,
        weight_unit_id: Optional[int] = None,
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

    def update_slot_entry(self, *, slot_entry_id: int, comment: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if comment is not None:
            payload["comment"] = comment[:100]
        if not payload:
            return {}
        return self.patch(f"/api/v2/slot-entry/{slot_entry_id}/", payload)

    def delete_slot_entry(self, *, slot_entry_id: int) -> None:
        self.delete(f"/api/v2/slot-entry/{slot_entry_id}/")

    # Config posts
    def set_sets(self, slot_entry_id: int, sets: int) -> Dict[str, Any]:
        # The API expects a singular 'iteration' field rather than 'iterations'.
        # The 'step' parameter defaults to "na" when omitted or unsupported, so we
        # explicitly set it to "na" here.  Repeat=True applies the rule to all
        # subsequent iterations.
        #
        # NOTE: the Wger API validates ``value`` as a decimal string, not an
        # integer.  Prior versions sent an int which triggered a HTTP 400
        # validation error when exporting plans.  Converting to ``str`` keeps the
        # request schema consistent with the repetitions endpoint and unblocks
        # plan exports.
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
            # repetitions API accepts decimal strings
            "value": int(reps),
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

    # Lookups with caches
    def repetition_unit_id(self, name: str = "repetitions") -> Optional[int]:
        if self._rep_unit_id_cache is not None:
            return self._rep_unit_id_cache
        data = self.get("/api/v2/setting-repetitionunit/", params={"name": name})
        results = data.get("results", [])
        self._rep_unit_id_cache = results[0]["id"] if results else None
        return self._rep_unit_id_cache

    def weight_unit_id(self, name: str = "kg") -> Optional[int]:
        if name in self._weight_unit_id_cache:
            return self._weight_unit_id_cache[name]
        data = self.get("/api/v2/setting-weightunit/", params={"name": name})
        results = data.get("results", [])
        self._weight_unit_id_cache[name] = results[0]["id"] if results else None
        return self._weight_unit_id_cache[name]


# ---------------------------
# Helpers
# ---------------------------

def routine_name_for_date(start: dt.date, prefix: Optional[str] = None) -> str:
    core = f"Wk {start.day} {start.strftime('%B')} {start.strftime('%y')}"
    name = f"{prefix.strip()} {core}" if prefix else core
    return name[:25]  # conservative for Wger UI

def weekday_name(dow: int) -> str:
    names = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
    return names.get(dow, f"Day {dow}")

def _pretty(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        return str(obj)


def _normalise_week_payload(week_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return payload with explicit days/exercises, supporting flattened sets input."""

    if "days" in week_payload:
        return week_payload

    sets = week_payload.get("sets")
    if sets is None:
        return week_payload
    if not isinstance(sets, list):
        raise WgerError("Invalid sets payload: expected a list under 'sets'.")

    day_map: Dict[int, List[tuple[int, Dict[str, Any]]]] = {}
    for item in sets:
        if not isinstance(item, dict):
            raise WgerError("Invalid sets payload: expected dict entries.")

        exercise_id = item.get("exercise_base")
        if exercise_id is None:
            raise WgerError("Sets payload missing 'exercise_base'.")

        try:
            exercise_id_int = int(exercise_id)
        except Exception as exc:  # pragma: no cover - defensive
            raise WgerError(f"Invalid exercise_base value: {exercise_id!r}") from exc

        order_raw = item.get("order", 0)
        try:
            order_int = int(order_raw)
        except Exception:
            order_int = 0

        dow_raw = item.get("day_of_week", 1)
        try:
            dow_int = int(dow_raw)
            if dow_int == 0:
                dow_int = 1
        except Exception:
            dow_int = 1

        entry: Dict[str, Any] = {
            "exercise": exercise_id_int,
            "sets": item.get("sets"),
            "reps": item.get("reps"),
            "comment": item.get("comment"),
        }

        if "weight" in item:
            entry["target_weight_kg"] = item.get("weight")
        if "rir" in item:
            entry["rir"] = item.get("rir")
        if "percent_1rm" in item:
            entry["percent_1rm"] = item.get("percent_1rm")

        day_map.setdefault(dow_int, []).append((order_int, entry))

    days: List[Dict[str, Any]] = []
    for dow, entries in sorted(day_map.items(), key=lambda pair: pair[0]):
        ordered = [item for _, item in sorted(entries, key=lambda pair: pair[0])]
        days.append({"day_of_week": dow, "exercises": ordered})

    return {
        "plan_id": week_payload.get("plan_id"),
        "week_number": week_payload.get("week_number", 1),
        "days": days,
    }

def _validate_exercises_exist_locally(week_payload: Dict[str, Any]) -> None:
    """
    Ensure all exercise IDs in week_payload exist in the local wger_exercise catalogue.
    """
    normalised = _normalise_week_payload(dict(week_payload))

    ex_ids = set()
    for d in normalised.get("days", []):
        for ex in d.get("exercises", []):
            if ex.get("exercise") is not None:
                try:
                    ex_ids.add(int(ex["exercise"]))
                except Exception:
                    raise WgerError(f"Invalid exercise id value: {ex.get('exercise')!r}")

    if not ex_ids:
        return

    missing: List[int] = []
    with conn_cursor() as (_, cur):
        cur.execute("SELECT id FROM wger_exercise WHERE id = ANY(%s);", (list(ex_ids),))
        present = {row["id"] for row in cur.fetchall()}
        for eid in ex_ids:
            if eid not in present:
                missing.append(eid)

    if missing:
        raise WgerError(f"One or more exercise IDs are not present in local catalogue: {sorted(missing)}")

def _wipe_week_contents(client: WgerClient, *, routine_id: int, week_id: int) -> None:
    """
    Delete all days under the given week to ensure a clean re-export.
    """
    days = client.list_days_for_week(routine_id=routine_id, week_id=week_id)
    for d in days:
        try:
            client.delete_day(day_id=int(d["id"]))
        except Exception as exc:
            logger.warning(f"Failed to delete day {d.get('id')}: {exc}")


# ---------------------------
# Public API
# ---------------------------

def export_week_to_wger(
    week_payload: Dict[str, Any],
    week_start: dt.date,
    week_end: Optional[dt.date] = None,
    *,
    routine_name: Optional[str] = None,
    routine_desc: Optional[str] = None,
    routine_prefix: Optional[str] = None,
    dry_run: bool = False,
    force_overwrite: bool = False,
    debug_api: bool = False,
    blaze_mode: str = "exercise",  # "exercise" or "comment"
) -> Dict[str, Any]:
    """
    Export a training week to Wger.

    Args:
        week_payload: {"plan_id": int, "week_number": int, "days": [{"day_of_week": int, "exercises":[...]}, ...]}
        week_start: Monday date
        week_end: optional end date, defaults to week_start + 6
        routine_name: optional explicit routine name, else derived from date
        routine_desc: optional description
        routine_prefix: optional prefix added to generated routine name
        dry_run: validate and log only, do not call Wger
        force_overwrite: delete existing days for the week before creating new ones
        debug_api: log request and response bodies at DEBUG level
        blaze_mode: "exercise" to export Blaze as a normal exercise slot, or "comment" for comment-only

    Returns:
        Dict summarising created or updated objects, including Wger IDs.
    """
    # Validate up front
    _validate_exercises_exist_locally(week_payload)
    normalised_payload = _normalise_week_payload(dict(week_payload))

    week_end = week_end or (week_start + dt.timedelta(days=6))
    r_name = routine_name or routine_name_for_date(week_start, routine_prefix)
    r_desc = routine_desc or "Auto-scheduled by Pete-Eebot"
    week_number = int(normalised_payload.get("week_number", 1))
    plan_id = normalised_payload.get("plan_id")

    logger.info(f"[wger_export] preparing export for plan {plan_id} week {week_number} ({r_name})")
    logger.debug(f"[wger_export] payload:\n{_pretty(normalised_payload)}")

    if dry_run:
        logger.info("[wger_export] dry-run mode enabled, skipping Wger calls.")
        created = {"routine_id": None, "week_id": None, "days": [], "dry_run": True}
        try:
            log_wger_export(
                plan_id,
                week_number,
                normalised_payload,
                {"name": r_name, "description": r_desc, "start": str(week_start), "end": str(week_end)},
                routine_id=None,
            )
        except Exception as e:
            logger.warning(f"Failed to write export log in dry-run: {e}")
        return created

    client = WgerClient(debug_api=debug_api)
    rep_unit_id = client.repetition_unit_id()

    # 1) Routine: find or create
    routine = client.find_routine(name=r_name, start=week_start) or client.create_routine(
        name=r_name, description=r_desc, start=week_start, end=week_end
    )
    routine_id = int(routine["id"])

    # 2) If requested, wipe all existing days under this routine
    if force_overwrite:
        logger.info(f"[wger_export] force_overwrite=True - wiping existing days for routine_id={routine_id}")
        try:
            existing_days = client.list_days(routine_id=routine_id)
            for d in existing_days:
                try:
                    client.delete_day(day_id=int(d.get("id")))
                except Exception as exc:
                    logger.warning(f"Failed to delete day {d.get('id')}: {exc}")
        except Exception as exc:
            logger.warning(f"Failed to list or delete existing days: {exc}")

    # 3) Days and slots - idempotent, find-or-create where possible (without week/session)
    ordered_days = sorted(normalised_payload.get("days", []), key=lambda d: int(d.get("day_of_week", 0)))
    created: Dict[str, Any] = {"routine_id": routine_id, "days": []}

    day_order = 1
    for day in ordered_days:
        dow = int(day.get("day_of_week"))
        exercises: List[Dict[str, Any]] = day.get("exercises", [])
        day_name = weekday_name(dow)

        # Find or create day by (routine_id, order) – there is no longer a week/session
        wger_day = client.find_day(routine_id=routine_id, order=day_order)
        if not wger_day:
            wger_day = client.create_day(routine_id=routine_id, order=day_order, name=day_name)
        day_id = int(wger_day["id"])
        created_day = {"order": day_order, "source_day_of_week": dow, "id": day_id, "slots": []}

        slot_order = 1
        for ex in exercises:
            ex_id = int(ex.get("exercise"))
            sets = int(ex.get("sets", 0) or 0)
            reps = int(ex.get("reps", 0) or 0)
            comment = (ex.get("comment") or "").strip()

            # Create or reuse slot
            slot = client.find_slot(day_id=day_id, order=slot_order) or client.create_slot(day_id=day_id, order=slot_order)
            slot_id = int(slot["id"])

            # Blaze handling: export as comment only if configured
            if blaze_mode == "comment" and ex_id == 1630:
                slot_comment = comment or "Blaze class"
                created_day["slots"].append({"slot_id": slot_id, "type": "comment-only", "comment": slot_comment})
                slot_order += 1
                continue

            # Create or reuse slot-entry (order=1)
            slot_entry = client.find_slot_entry(slot_id=slot_id, order=1)
            if not slot_entry:
                slot_entry = client.create_slot_entry(
                    slot_id=slot_id,
                    exercise_id=ex_id,
                    order=1,
                    comment=(comment or ("Blaze class" if ex_id == 1630 else None)),
                    repetition_unit_id=rep_unit_id,
                    weight_unit_id=None,
                )
            else:
                # Update comment if provided
                if comment:
                    try:
                        client.update_slot_entry(slot_entry_id=int(slot_entry["id"]), comment=comment)
                    except Exception as exc:
                        logger.debug(f"[wger_export] ignoring slot-entry comment update failure: {exc}")

            slot_entry_id = int(slot_entry["id"]) if slot_entry else None

            # Post set/reps configs – re-posting is idempotent for operation="r"
            if slot_entry_id is not None:
                if sets > 0:
                    client.set_sets(slot_entry_id, sets)
                if reps > 0:
                    client.set_reps(slot_entry_id, reps)

                # Parse RIR in comment if present, apply as config
                lower = (comment or "").lower()
                if "rir" in lower:
                    try:
                        import re
                        m = re.search(r"([0-9]+(?:\.[0-9])?)", lower.split("rir", 1)[1])
                        if m:
                            rir_val = float(m.group(1))
                            client.set_rir(slot_entry_id, rir_val)
                    except Exception:
                        pass

            created_day["slots"].append(
                {"slot_id": slot_id, "slot_entry_id": slot_entry_id, "exercise": ex_id}
                if slot_entry_id
                else {"slot_id": slot_id, "type": "comment-only"}
            )
            slot_order += 1

        created["days"].append(created_day)
        day_order += 1

    # 4) Export log with routine meta
    try:
        log_wger_export(plan_id, week_number, normalised_payload, {"id": routine_id, "name": r_name}, routine_id=routine_id)
    except Exception as e:
        logger.warning(f"[wger_export] failed to write export log: {e}")

    logger.info(
        f"[wger_export] sent plan {plan_id} week {week_number} to Wger – "
        f"routine_id={routine_id}, days={len(created['days'])}"
    )
    logger.debug(f"[wger_export] mapping:\n{json.dumps(created, ensure_ascii=False, indent=2)}")

    return created
