#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Apply a plan JSON to build a Routine on wger.de.

Highlights
- Accepts your legacy schema: {"routine": {"start","end",...}, "days":[...]}
  and dated variants; per‑day "date" is NOT required.
- Routine name is derived from the date range (<= 25 chars), e.g. "01–28 Sep 2025".
- Falls back to https://wger.de/api/v2 if WGER_BASE_URL is unset/empty.
- Creates days → slots → exercises using /routine/, /day/, /slot/, /slot-entry/
  (retries w/o order and falls back to /slotconfig/ if needed).
- Writes configs via /sets-config/, /repetitions-config/, /max-repetitions-config/,
  /weight-config/, /rir-config/, /rest-config/.
- **FIX:** Builds the exercise index from /exerciseinfo/ (reads English translation),
  avoiding KeyError 'name' seen with /exercise/ on the public server.
"""

from __future__ import annotations
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

# ---------- Environment & HTTP ----------

BASE = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").rstrip("/")
API_KEY = (os.environ.get("WGER_API_KEY") or "").strip()

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}
if API_KEY:
    HEADERS["Authorization"] = f"Token {API_KEY}"

def log(msg: str) -> None:
    print(msg, flush=True)

def _truncate(s: str, n: int = 800) -> str:
    return s if len(s) <= n else s[:n] + "…"

def _req(method: str, url: str, json_payload: Optional[Dict[str, Any]] = None,
         ok=(200, 201), tries=2, backoff=0.6) -> requests.Response:
    last = None
    for i in range(tries):
        r = requests.request(method, url, headers=HEADERS, json=json_payload, timeout=60)
        if r.status_code in ok:
            return r
        log(f"[ERROR] {method} {url} -> {r.status_code}: {_truncate(r.text)}")
        last = r
        if 500 <= r.status_code < 600 and i < tries - 1:
            time.sleep(backoff)
            continue
        r.raise_for_status()
    assert last is not None
    last.raise_for_status()
    return last

def GET(path_or_url: str) -> Dict[str, Any]:
    url = path_or_url if path_or_url.startswith("http") else f"{BASE}{path_or_url}"
    return _req("GET", url, ok=(200,)).json()

def POST(path: str, payload: Dict[str, Any], ok=(201,)) -> Dict[str, Any]:
    return _req("POST", f"{BASE}{path}", json_payload=payload, ok=ok).json()

# ---------- Name & reps helpers ----------

MAX_ROUTINE_NAME = 25

def routine_name_from_dates(start: str, end: str) -> str:
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    if s.year == e.year and s.month == e.month:
        name = f"{s.day:02d}–{e.day:02d} {s.strftime('%b %Y')}"   # e.g., 01–28 Sep 2025
    else:
        name = f"{s.strftime('%d %b %Y')}–{e.strftime('%d %b %Y')}"
    if len(name) > MAX_ROUTINE_NAME:
        name = name.replace(" ", "")
    return name[:MAX_ROUTINE_NAME]

def parse_reps(v: Any) -> Optional[Tuple[int, Optional[int]]]:
    if v is None: return None
    if isinstance(v, int): return (v, None)
    if isinstance(v, str):
        s = v.strip()
        if "-" in s:
            a, b = s.split("-", 1)
            try: return (int(a), int(b))
            except: return None
        try: return (int(s), None)
        except: return None
    if isinstance(v, dict):
        mn, mx = v.get("min"), v.get("max")
        if isinstance(mn, int) and (mx is None or isinstance(mx, int)):
            return (mn, mx)
    return None

# ---------- Exercise index (from /exerciseinfo/) ----------

def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

ALIASES = {
    "barbellbentoverrow": ["bentoverbarbellrow","bentoverrowbarbell","barbellrow"],
    "barbelloverheadpress": ["overheadpress","militarypress","ohp","standingbarbellpress"],
    "hangingkneeraise": ["hanginglegraise","verticalkneeraise","captainschairkneeraise"],
}

def build_exercise_index(language_id: int = 2) -> Tuple[Dict[str, List[int]], Dict[int, str]]:
    """
    Build name→ids and id→name using /exerciseinfo/ (translations include language-specific names).
    """
    log("[index] Loading exercises from /exerciseinfo/ …")
    name_index: Dict[str, List[int]] = {}
    id_to_name: Dict[int, str] = {}

    url = f"/exerciseinfo/?limit=100"
    while url:
        page = GET(url)
        for row in page.get("results", []):
            ex_id = int(row["id"])
            # pick English name from translations
            en_name = None
            for tr in row.get("translations", []):
                if tr.get("language") == language_id and tr.get("name"):
                    en_name = tr["name"]; break
            if not en_name:
                # fallback: sometimes the base has a name
                en_name = row.get("name") or None
            if not en_name:
                continue
            key = normalize(en_name)
            id_to_name[ex_id] = en_name
            name_index.setdefault(key, []).append(ex_id)

        url = page.get("next") or ""
        # next may be absolute; keep as-is for GET()

    log(f"[index] Loaded {len(id_to_name)} exercises")
    return name_index, id_to_name

def resolve_exercise_id(name_index: Dict[str, List[int]], name: str) -> Optional[int]:
    key = normalize(name)
    if key in name_index:
        return name_index[key][0]
    for alt in ALIASES.get(key, []):
        if alt in name_index:
            return name_index[alt][0]
    # fuzzy match
    keys = list(name_index.keys())
    match = difflib.get_close_matches(key, keys, n=1, cutoff=0.74)
    return name_index[match[0]][0] if match else None

# ---------- Plan loader (supports your legacy schema) ----------

def load_plan(path: str) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Returns (start, end, days)
    Days: [{"name": str, "is_rest": bool, "slots":[{"order": int, "exercises":[{...}]}]}]
    Does NOT require per-day "date".
    """
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    # Legacy weekly-cycle: {"routine": {...}, "days":[...]}
    if isinstance(doc, dict) and "routine" in doc and "days" in doc:
        r = doc["routine"] or {}
        start = r.get("start") or r.get("start_date")
        end   = r.get("end")   or r.get("end_date")
        if not start or not end:
            raise ValueError("Plan.routine.start and Plan.routine.end are required.")
        days_src = doc.get("days") or []

        days_out: List[Dict[str, Any]] = []
        for idx, d in enumerate(days_src, start=1):
            name = (d.get("name") or f"Day {idx}")[:50]
            is_rest = bool(d.get("is_rest", False))

            # If the legacy entry has a flat "exercises" list, wrap into one slot
            if d.get("slots"):
                slots = d["slots"]
            elif d.get("exercises"):
                slots = [{"order": 1, "exercises": d["exercises"]}]
            else:
                slots = []

            days_out.append({"name": name, "is_rest": is_rest, "slots": slots})
        return start, end, days_out

    # Object with days + top-level dates
    if isinstance(doc, dict) and "days" in doc:
        days_src = doc["days"]
        start = doc.get("start") or doc.get("start_date")
        end   = doc.get("end")   or doc.get("end_date")
        if not start or not end:
            # Try to infer from per-day date fields
            try:
                ds = [d["date"] for d in days_src if "date" in d]
                start, end = min(ds), max(ds)
            except Exception:
                raise ValueError("Plan missing start/end and days lack 'date' fields.")
        days_out: List[Dict[str, Any]] = []
        for idx, d in enumerate(days_src, start=1):
            name = (d.get("name") or f"Day {idx}")[:50]
            is_rest = bool(d.get("is_rest", False))
            slots = d.get("slots") or [{"order": 1, "exercises": d.get("exercises", [])}]
            days_out.append({"name": name, "is_rest": is_rest, "slots": slots})
        return start, end, days_out

    # List-of-days
    if isinstance(doc, list):
        days_src = doc
        try:
            ds = [d["date"] for d in days_src if "date" in d]
            start, end = min(ds), max(ds)
        except Exception:
            raise ValueError("List plan requires per-day 'date' OR provide an object with start/end.")
        days_out: List[Dict[str, Any]] = []
        for idx, d in enumerate(days_src, start=1):
            name = (d.get("name") or f"Day {idx}")[:50]
            is_rest = bool(d.get("is_rest", False))
            slots = d.get("slots") or [{"order": 1, "exercises": d.get("exercises", [])}]
            days_out.append({"name": name, "is_rest": is_rest, "slots": slots})
        return start, end, days_out

    raise ValueError("Unrecognized plan format.")

# ---------- Endpoint discovery ----------

def discover_endpoints() -> Dict[str, str]:
    root = GET("/")
    keys = [
        "routine","day","slot","slot-entry","slotconfig",
        "sets-config","max-sets-config","repetitions-config","max-repetitions-config",
        "weight-config","max-weight-config","rir-config","max-rir-config",
        "rest-config","max-rest-config","exerciseinfo"
    ]
    return {k: root[k] for k in keys if k in root}

# ---------- Builders ----------

def create_routine(start: str, end: str, description: str = "", fit_in_week: bool = False) -> int:
    name = routine_name_from_dates(start, end)  # per your request
    payload = {"name": name[:MAX_ROUTINE_NAME], "start": start, "end": end, "fit_in_week": bool(fit_in_week)}
    if description: payload["description"] = description[:1000]
    res = POST("/routine/", payload)
    rid = int(res["id"])
    log(f"[OK] Created routine id={rid} name={payload['name']}")
    return rid

def create_day(routine_id: int, order: int, name: str, is_rest: bool, description: str = "") -> int:
    payload = {"routine": routine_id, "order": int(order), "name": name[:50], "is_rest": bool(is_rest)}
    if description: payload["description"] = description[:250]
    res = POST("/day/", payload)
    did = int(res["id"])
    log(f"  [day] {order} {name} → id={did} rest={is_rest}")
    return did

def create_slot(day_id: int, order: int) -> int:
    res = POST("/slot/", {"day": day_id, "order": int(order)})
    sid = int(res["id"])
    log(f"    [slot] order={order} id={sid}")
    return sid

def create_slot_entry(endpoints: Dict[str, str], slot_id: int, exercise_id: int, order: int) -> Tuple[str, int]:
    """
    Try /slot-entry/ (preferred), retry without order if needed, else fallback /slotconfig/.
    Returns (link_kind, link_id) where link_kind in {"slot-entry","slotconfig"}.
    """
    if "slot-entry" in endpoints:
        # Attempt with order
        try:
            res = POST("/slot-entry/", {"slot": slot_id, "exercise": exercise_id, "order": int(order)}, ok=(201,))
            sid = int(res["id"]); log(f"      [entry] slot_entry_id={sid} ex={exercise_id}")
            return ("slot-entry", sid)
        except Exception:
            # Retry without order
            try:
                res = POST("/slot-entry/", {"slot": slot_id, "exercise": exercise_id}, ok=(201,))
                sid = int(res["id"]); log(f"      [entry] slot_entry_id={sid} ex={exercise_id} (no order)")
                return ("slot-entry", sid)
            except Exception as e:
                log(f"      [WARN] /slot-entry/ failed twice; trying /slotconfig/ fallback ({e})")

    if "slotconfig" in endpoints:
        res = POST("/slotconfig/", {"slot": slot_id, "exercise": exercise_id}, ok=(201,))
        scid = int(res["id"]); log(f"      [entry] slot_config_id={scid} ex={exercise_id}")
        return ("slotconfig", scid)

    raise RuntimeError("Server lacks both /slot-entry/ and /slotconfig/ endpoints.")

def post_config_row(path: str, link_kind: str, link_id: int, value: Any) -> None:
    """
    Servers differ on FK field names; try common variants.
    """
    fk_order = ["slot_entry","slot_config","slot"]
    pref = ["slot_entry","slot"] if link_kind == "slot-entry" else ["slot_config","slot"]
    tried = []
    for fk in pref + [k for k in fk_order if k not in pref]:
        payload = {"value": value, fk: link_id}
        try:
            POST(path, payload, ok=(201,))
            return
        except Exception as e:
            tried.append(fk); last = e
    log(f"        [WARN] Config POST {path} failed (tried {tried}): {last}")

def set_configs(link_kind: str, link_id: int,
                sets: Optional[int], reps: Optional[Tuple[int, Optional[int]]],
                weight: Optional[float], rir: Optional[int], rest_sec: Optional[int]) -> None:
    if sets is not None:
        post_config_row("/sets-config/", link_kind, link_id, int(sets))
    if reps is not None:
        lo, hi = reps
        post_config_row("/repetitions-config/", link_kind, link_id, int(lo))
        if hi is not None and int(hi) != int(lo):
            post_config_row("/max-repetitions-config/", link_kind, link_id, int(hi))
    if weight is not None:
        post_config_row("/weight-config/", link_kind, link_id, float(weight))
    if rir is not None:
        post_config_row("/rir-config/", link_kind, link_id, int(rir))
    if rest_sec is not None:
        post_config_row("/rest-config/", link_kind, link_id, int(rest_sec))

# ---------- Build from plan ----------

def build_from_plan(plan_path: str) -> None:
    log(f"[wger] Base URL: {BASE}")
    log(f"[wger] Dry run: NO")
    log(f"[wger] Reading plan: {plan_path}")

    start, end, days = load_plan(plan_path)
    endpoints = discover_endpoints()

    # Exercise index (English) from /exerciseinfo/
    name_index, _ = build_exercise_index(language_id=2)

    rid = create_routine(start=start, end=end, description="", fit_in_week=False)

    # Build days → slots → entries
    for di, day in enumerate(days, start=1):
        did = create_day(routine_id=rid, order=di, name=day["name"], is_rest=bool(day["is_rest"]))
        if day["is_rest"]:
            continue

        slots = day.get("slots") or [{"order": 1, "exercises": day.get("exercises", [])}]
        for si, slot in enumerate(slots, start=1):
            sid = create_slot(day_id=did, order=int(slot.get("order") or si))

            items = slot.get("exercises") or slot.get("items") or []
            for ei, item in enumerate(items, start=1):
                ex_id = item.get("exercise_id")
                if not ex_id:
                    name = item.get("name") or item.get("exercise_name")
                    if not name:
                        log("      [WARN] Skipping: missing 'name' or 'exercise_id'")
                        continue
                    ex_id = resolve_exercise_id(name_index, name)
                    if not ex_id:
                        log(f"      [WARN] Could not resolve exercise_id for '{name}'. Skipping.")
                        continue

                link_kind, link_id = create_slot_entry(endpoints, slot_id=sid, exercise_id=int(ex_id), order=ei)

                sets = item.get("sets"); sets = int(sets) if sets is not None else None
                reps = parse_reps(item.get("reps"))
                weight = item.get("weight")
                if weight is not None:
                    try: weight = float(weight)
                    except: weight = None
                rir = int(item.get("rir")) if item.get("rir") is not None else None
                rest_sec = item.get("rest") or item.get("rest_seconds") or item.get("rest_sec")
                if rest_sec is not None:
                    try: rest_sec = int(rest_sec)
                    except: rest_sec = None

                set_configs(link_kind, link_id, sets=sets, reps=reps, weight=weight, rir=rir, rest_sec=rest_sec)

    log("[OK] Routine build completed.")

# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="Apply a plan JSON to wger Routine API (public server compatible)")
    ap.add_argument("plan", help="Path to plan JSON")
    args = ap.parse_args()
    build_from_plan(args.plan)

if __name__ == "__main__":
    main()