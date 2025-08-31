#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Builds a Routine on wger from a plan JSON.

Key fixes vs previous attempts:
- Uses /exercise/ to resolve exercise IDs (language=2), not exerciseinfo.
- Creates exercises via /slot-entry/ (the public wger.de API root exposes this),
  and adds an explicit 'order'. Falls back to /slotconfig/ only if needed.
- Sets sets/reps/weight/RIR/rest via the dedicated *-config endpoints.
- Routine name is auto-generated from the date range and hard-limited to 25 chars.
- No calls to deprecated/nonexistent endpoints like repetition-unit.

Plan JSON supported (either format):

A) List-of-days:
[
  {
    "date": "2025-09-01",
    "name": "Lower",
    "is_rest": false,
    "slots": [
      {
        "order": 1,
        "label": "Main",
        "exercises": [
          {"name": "Barbell Back Squat", "sets": 5, "reps": "5", "weight": 60, "rir": 2, "rest": 120}
        ]
      }
    ]
  },
  ...
]

B) Object with meta:
{
  "start": "2025-09-01",
  "end": "2025-09-28",
  "name": "optional",
  "days": [ ...same as above... ]
}

Exercise items can also include "exercise_id" to bypass name matching.
"""

import argparse
import datetime as dt
import difflib
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

# --------- Config & HTTP helpers ---------

BASE = os.environ.get("WGER_BASE_URL", "https://wger.de/api/v2").rstrip("/")
API_KEY = os.environ.get("WGER_API_KEY", "").strip()
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}
if API_KEY:
    # Public server still accepts permanent tokens via "Token ..." header.
    HEADERS["Authorization"] = f"Token {API_KEY}"

def log(msg: str) -> None:
    print(msg, flush=True)

def _truncate(s: str, n: int = 600) -> str:
    return s if len(s) <= n else s[:n] + "…"

def req(method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        ok: Tuple[int, ...] = (200, 201),
        tries: int = 2,
        backoff: float = 0.7) -> requests.Response:
    last = None
    for i in range(tries):
        r = requests.request(method, url, headers=HEADERS, json=payload, timeout=60)
        if r.status_code in ok:
            return r
        # Log once per attempt; only retry on 5xx
        log(f"[ERROR] {method} {url} -> {r.status_code}: {_truncate(r.text)}")
        last = r
        if 500 <= r.status_code < 600 and i < tries - 1:
            time.sleep(backoff)
            continue
        r.raise_for_status()
    assert last is not None
    last.raise_for_status()
    return last  # never reached

def GET(path_or_url: str) -> Dict[str, Any]:
    url = path_or_url if path_or_url.startswith("http") else f"{BASE}{path_or_url}"
    return req("GET", url, ok=(200,)).json()

def POST(path: str, payload: Dict[str, Any], ok: Tuple[int, ...] = (201,)) -> Dict[str, Any]:
    return req("POST", f"{BASE}{path}", payload=payload, ok=ok).json()

# --------- Utilities ---------

def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())

ALIASES = {
    # common alias fixes
    "barbellbentoverrow": ["bentoverbarbellrow", "barbellbentoverrow", "bentoverrowbarbell"],
    "barbelloverheadpress": ["militarypress", "overheadpress", "shoulderpressbarbell", "standingbarbellpress"],
    "hangingkneeraise": ["hanginglegraise", "verticalkneeraise", "captainschairkneeraise"],
}

def routine_name_from_dates(start: str, end: str) -> str:
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    if s.year == e.year and s.month == e.month:
        name = f"{s.day:02d}–{e.day:02d} {s.strftime('%b %Y')}"  # e.g. 01–28 Sep 2025
    else:
        name = f"{s.strftime('%d %b %Y')}–{e.strftime('%d %b %Y')}"
    # wger.de currently enforces 25 chars -> trim safely
    if len(name) > 25:
        name = name.replace(" ", "")
    return name[:25]

def paginate(url: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    while url:
        r = req("GET", url, ok=(200,))
        data = r.json()
        items.extend(data.get("results", []))
        url = data.get("next")
    return items

# --------- Index building ---------

def build_exercise_index(language_id: int = 2) -> Tuple[Dict[str, List[int]], Dict[int, str]]:
    """
    Builds:
      - name_index: normalized exercise name -> list of exercise IDs (language-specific)
      - id_to_name: exercise_id -> exercise name
    """
    log("[index] Loading exercises from /exercise/ …")
    first = GET(f"/exercise/?limit=200&language={language_id}&status=2")
    total = first.get("count", 0)
    url = first.get("next")
    results = first.get("results", [])
    # paginate if needed
    if url:
        results.extend(paginate(url))
    log(f"[index] Loaded {len(results)} exercises (reported count={total})")

    name_index: Dict[str, List[int]] = {}
    id_to_name: Dict[int, str] = {}

    for ex in results:
        ex_id = int(ex["id"])
        name = ex["name"]
        key = normalize(name)
        id_to_name[ex_id] = name
        name_index.setdefault(key, []).append(ex_id)

    return name_index, id_to_name

def resolve_exercise_id(name_index: Dict[str, List[int]], name: str) -> Optional[int]:
    key = normalize(name)
    if key in name_index:
        return name_index[key][0]
    # try aliases
    for alt in ALIASES.get(key, []):
        if alt in name_index:
            return name_index[alt][0]
    # fuzzy best match
    keys = list(name_index.keys())
    matches = difflib.get_close_matches(key, keys, n=1, cutoff=0.74)
    if matches:
        return name_index[matches[0]][0]
    return None

# --------- Plan parsing ---------

def load_plan(path: str) -> Tuple[str, str, str, List[Dict[str, Any]]]:
    """
    Returns (start, end, routine_name, days)
    Each day has: {date, name, is_rest, slots:[{order,label,exercises:[{...}]}]}
    If routine_name is empty, caller will generate from dates.
    """
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    if isinstance(doc, list):
        days = doc
        start = min(d["date"] for d in days)
        end = max(d["date"] for d in days)
        routine_name = ""
    elif isinstance(doc, dict) and "days" in doc:
        days = doc["days"]
        start = doc.get("start") or min(d["date"] for d in days)
        end = doc.get("end") or max(d["date"] for d in days)
        routine_name = doc.get("name", "") or ""
    else:
        raise ValueError("Plan JSON must be a list of days or an object with a 'days' key.")

    # Normalize/guard fields
    norm_days: List[Dict[str, Any]] = []
    for i, d in enumerate(days, start=1):
        date = d["date"]
        is_rest = bool(d.get("is_rest", False))
        day_name = d.get("name") or d.get("title") or ("Rest" if is_rest else f"Day {i}")
        slots = d.get("slots")

        # Fallback: if no explicit slots but there is a flat 'exercises' list, wrap it
        if not slots and d.get("exercises"):
            slots = [{"order": 1, "label": "Main", "exercises": d["exercises"]}]

        norm_days.append({
            "date": date,
            "name": day_name,
            "is_rest": is_rest,
            "slots": slots or [],
        })

    return start, end, routine_name, norm_days

# --------- Endpoint discovery ---------

def discover_endpoints() -> Dict[str, str]:
    """
    Reads the API root to determine available endpoints on the target server.
    """
    root = GET("/")

    # Flatten only those we care about
    want = [
        "routine", "day", "slot", "slot-entry",
        "weight-config", "max-weight-config",
        "repetitions-config", "max-repetitions-config",
        "sets-config", "max-sets-config",
        "rest-config", "max-rest-config",
        "rir-config", "max-rir-config",
        "exercise", "exerciseinfo"
    ]
    present = {}
    for k in want:
        if k in root:
            present[k] = root[k]
    return present

# --------- Builders ---------

def create_routine(name: str, start: str, end: str, description: str = "", fit_in_week: bool = False) -> int:
    payload = {
        "name": name[:25],  # server enforces 25 on wger.de
        "start": start,
        "end": end,
        "fit_in_week": bool(fit_in_week),
    }
    if description:
        payload["description"] = description[:1000]
    res = POST("/routine/", payload)
    rid = int(res["id"])
    log(f"[OK] Created routine id={rid} name={payload['name']}")
    return rid

def create_day(routine_id: int, order: int, name: str, is_rest: bool, description: str = "") -> int:
    payload = {
        "routine": routine_id,
        "order": int(order),
        "name": name[:50],
        "is_rest": bool(is_rest),
    }
    if description:
        payload["description"] = description[:250]
    res = POST("/day/", payload)
    did = int(res["id"])
    log(f"  [day] {order} {name} → id={did} is_rest={is_rest}")
    return did

def create_slot(day_id: int, order: int) -> int:
    payload = {"day": day_id, "order": int(order)}
    res = POST("/slot/", payload)
    sid = int(res["id"])
    log(f"    [slot] order={order} id={sid}")
    return sid

def create_slot_entry_or_config(endpoints: Dict[str, str], slot_id: int, exercise_id: int, order: int) -> Tuple[str, int]:
    """
    Creates the relation between slot and exercise.

    Returns (kind, id) where kind ∈ {"slot-entry", "slotconfig"} to know which
    foreign key to use when posting config rows later.
    """
    if "slot-entry" in endpoints:
        try:
            payload = {"slot": slot_id, "exercise": exercise_id, "order": int(order)}
            res = POST("/slot-entry/", payload, ok=(201,))
            sid = int(res["id"])
            log(f"      [entry] exercise={exercise_id} → slot_entry_id={sid}")
            return ("slot-entry", sid)
        except Exception:
            log("      [WARN] /slot-entry/ failed; will try /slotconfig/ fallback")

    # Fallback to /slotconfig/ if server supports it (older/newer versions differ)
    try:
        res = POST("/slotconfig/", {"slot": slot_id, "exercise": exercise_id}, ok=(201,))
        scid = int(res["id"])
        log(f"      [entry] (slotconfig) exercise={exercise_id} → slot_config_id={scid}")
        return ("slotconfig", scid)
    except Exception as e:
        log(f"      [ERROR] failed to add exercise {exercise_id} to slot {slot_id}: {e}")
        raise

def post_config_row(path: str, link_kind: str, link_id: int, value: Any) -> None:
    """
    Try acceptable foreign key names in order, depending on how the server expects them.
    """
    fk_order = ["slot_entry", "slot_config", "slot"]
    payload_base = {"value": value}
    # prefer key implied by creation path
    if link_kind == "slot-entry":
        pref = ["slot_entry", "slot", "slot_config"]
    else:
        pref = ["slot_config", "slot", "slot_entry"]
    tried = []
    for fk in (pref + [k for k in fk_order if k not in pref]):
        payload = dict(payload_base)
        payload[fk] = link_id
        try:
            POST(path, payload, ok=(201,))
            return
        except Exception as e:
            tried.append(fk)
            last_err = e
    log(f"        [WARN] Config POST {path} failed for keys {tried}; last error: {last_err}")

def set_configs(link_kind: str, link_id: int,
                sets: Optional[int] = None,
                reps: Optional[Tuple[int, Optional[int]]] = None,
                weight: Optional[float] = None,
                rir: Optional[int] = None,
                rest_sec: Optional[int] = None) -> None:
    """
    Adds configuration rows for the created slot entry.
    """
    # sets
    if sets is not None:
        post_config_row("/sets-config/", link_kind, link_id, int(sets))
    # reps (min, max?)
    if reps is not None:
        minr, maxr = reps
        post_config_row("/repetitions-config/", link_kind, link_id, int(minr))
        if maxr is not None and int(maxr) != int(minr):
            post_config_row("/max-repetitions-config/", link_kind, link_id, int(maxr))
    # weight (kg)
    if weight is not None:
        post_config_row("/weight-config/", link_kind, link_id, float(weight))
    # RIR
    if rir is not None:
        post_config_row("/rir-config/", link_kind, link_id, int(rir))
    # rest (seconds)
    if rest_sec is not None:
        post_config_row("/rest-config/", link_kind, link_id, int(rest_sec))

def parse_reps(value: Any) -> Optional[Tuple[int, Optional[int]]]:
    """
    Accepts: 8, "8", "6-8", {"min":6,"max":8}
    """
    if value is None:
        return None
    if isinstance(value, int):
        return (value, None)
    if isinstance(value, str):
        v = value.strip()
        if "-" in v:
            a, b = v.split("-", 1)
            try:
                return (int(a), int(b))
            except:
                return None
        try:
            return (int(v), None)
        except:
            return None
    if isinstance(value, dict):
        mn = value.get("min")
        mx = value.get("max")
        if isinstance(mn, int) and (mx is None or isinstance(mx, int)):
            return (mn, mx)
    return None

# --------- Main build pipeline ---------

def build_from_plan(plan_path: str, routine_name_override: str = "", dry_run: bool = False) -> None:
    log(f"[wger] Base URL: {BASE}")
    log(f"[wger] Dry run: {'YES' if dry_run else 'NO'}")
    log(f"[wger] Reading plan: {plan_path}")

    start, end, plan_name, days = load_plan(plan_path)
    name = routine_name_override or plan_name or routine_name_from_dates(start, end)
    name = name[:25]  # enforce

    endpoints = discover_endpoints()

    # Build exercise index from /exercise/
    name_index, id_to_name = build_exercise_index(language_id=2)

    if dry_run:
        log(f"[DRY] Would create routine '{name}' {start}→{end} with {len(days)} days")
        return

    rid = create_routine(name=name, start=start, end=end, description="", fit_in_week=False)

    for di, day in enumerate(days, start=1):
        did = create_day(routine_id=rid,
                         order=di,
                         name=day["name"],
                         is_rest=bool(day["is_rest"]),
                         description="")
        if day["is_rest"]:
            continue

        slots = day.get("slots", [])
        if not slots:
            # If no slots provided, create a single empty slot to keep structure
            slots = [{"order": 1, "label": "Main", "exercises": day.get("exercises", [])}]

        for si, slot in enumerate(slots, start=1):
            sid = create_slot(day_id=did, order=int(slot.get("order") or si))

            items = slot.get("exercises", []) or slot.get("items", [])
            for ei, item in enumerate(items, start=1):
                # Resolve exercise id
                ex_id = item.get("exercise_id")
                if not ex_id:
                    ex_name = item.get("name") or item.get("exercise_name")
                    if not ex_name:
                        log("      [WARN] Skipping entry without 'name' or 'exercise_id'")
                        continue
                    ex_id = resolve_exercise_id(name_index, ex_name)
                    if not ex_id:
                        log(f"      [WARN] Could not resolve exercise_id for '{ex_name}'. Skipping.")
                        continue

                kind, link_id = create_slot_entry_or_config(endpoints, slot_id=sid, exercise_id=int(ex_id), order=ei)

                # Configs
                sets = item.get("sets")
                reps = parse_reps(item.get("reps"))
                weight = item.get("weight")
                rir = item.get("rir")
                rest_sec = item.get("rest") or item.get("rest_sec") or item.get("rest_seconds")

                set_configs(kind, link_id, sets=sets, reps=reps, weight=weight, rir=rir, rest_sec=rest_sec)

    log("[OK] Routine build completed.")

# --------- CLI ---------

def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply a plan JSON to wger Routine API")
    p.add_argument("plan", help="Path to plan JSON")
    p.add_argument("--dry-run", action="store_true", help="Print actions without posting")
    p.add_argument("--routine-name", help="Override routine name", default="")
    return p.parse_args(argv)

def main() -> None:
    args = parse_args(sys.argv[1:])
    build_from_plan(args.plan, routine_name_override=args.routine_name, dry_run=args.dry_run)

if __name__ == "__main__":
    main()