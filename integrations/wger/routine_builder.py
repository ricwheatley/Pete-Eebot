#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Routine builder for WGER (public wger.de API).

What this script does
---------------------
- Reads a 4-week plan JSON and creates a Routine with Days, Slots, Slot-Entries (exercises),
  then attaches numeric configs for sets, reps (+unit), weight (+unit), rest and RIR.
- Resolves exercise names by fetching the live /api/v2/exerciseinfo/ index (English),
  doing robust normalization + fuzzy matching with equipment/category hints.
- Works against the public server (wger.de) which uses `/slot-entry/` (not `/slotconfig/`).

Inputs
------
- PLAN JSON path (see format notes below)
- Environment:
  WGER_API_KEY  : Personal token (required)
  WGER_BASE_URL : Optional (default https://wger.de/api/v2)

Plan JSON shape (example)
-------------------------
{
  "routine_name": "PeteE. Block 2025-09-01–2025-09-28",
  "start_date": "2025-09-01",
  "end_date":   "2025-09-28",
  "days": [
    {
      "date": "2025-09-01",
      "name": "Lower",
      "is_rest": false,
      "slots": [
        {
          "order": 1,
          "items": [
            {
              "name": "Back Squat",
              "equipment": "Barbell",           # optional but helps matching
              "category": "Legs",               # optional but helps matching
              "sets": 5,
              "reps": 5,
              "weight": 60.0,                   # kg unless you change default unit
              "rest_seconds": 120,
              "rir": 2
            }
          ]
        }
      ]
    },
    {
      "date": "2025-09-02",
      "name": "Blaze HIIT @ 07:00",
      "is_rest": false,
      "class_placeholder": true               # if true -> creates a titled day without slots
    }
  ]
}

Notes
-----
- Any day with "class_placeholder": true will be created without slots; it still appears in the routine
  so your calendar shows the class (title comes from "name").
- If weight/reps/sets are omitted, defaults will be posted so the app won’t see nulls.
- Units: defaults to kg + reps; can be changed via REPS_UNIT_NAME / WEIGHT_UNIT_NAME constants below.
"""

from __future__ import annotations
import argparse, os, sys, json, time, re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import requests

# ---------- Config ----------
DEFAULT_BASE = "https://wger.de/api/v2"
REPS_UNIT_NAME = "reps"   # will be looked up via /repetition-unit/
WEIGHT_UNIT_NAME = "kg"   # will be looked up via /weightunit/
HTTP_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_SLEEP = 1.0

# ---------- Logging ----------
def info(msg: str):  print(msg, flush=True)
def warn(msg: str):  print(f"[WARN] {msg}", flush=True)
def err(msg: str):   print(f"[ERROR] {msg}", flush=True)

# ---------- HTTP helpers ----------
def get_env() -> Tuple[str, Dict[str,str]]:
    base = os.environ.get("WGER_BASE_URL", DEFAULT_BASE).rstrip("/")
    key  = os.environ.get("WGER_API_KEY", "").strip()
    if not key:
        err("WGER_API_KEY not set")
        sys.exit(1)
    headers = {
        "Authorization": f"Token {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return base, headers

def req(method: str, url: str, headers: Dict[str,str], payload: Optional[Dict[str,Any]]=None, params: Optional[Dict[str,Any]]=None, ok=(200,201), dry_run=False) -> requests.Response:
    for attempt in range(1, MAX_RETRIES+1):
        try:
            if dry_run and method.upper() in ("POST","PUT","PATCH","DELETE"):
                info(f"DRY RUN {method} {url} {('params='+str(params)) if params else ''} {('payload='+json.dumps(payload)) if payload else ''}")
                class Dummy:
                    status_code=200
                    def json(self): return {"dry_run": True}
                    def raise_for_status(self): return
                return Dummy()  # type: ignore
            r = requests.request(method.upper(), url, headers=headers, json=payload, params=params, timeout=HTTP_TIMEOUT)
            if r.status_code not in ok:
                try:
                    body = r.text
                except Exception:
                    body = "<no body>"
                err(f"{method} {url} -> {r.status_code}: {body[:600]}")
                r.raise_for_status()
            return r
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_SLEEP)

def GET(base: str, headers: Dict[str,str], path: str, params: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    return req("GET", f"{base}{path}", headers, params=params).json()

def POST(base: str, headers: Dict[str,str], path: str, payload: Dict[str,Any], ok=(201,), dry_run=False) -> Dict[str,Any]:
    return req("POST", f"{base}{path}", headers, payload=payload, ok=ok, dry_run=dry_run).json()

# ---------- Models ----------
@dataclass
class PlanItem:
    name: str
    equipment: Optional[str] = None
    category: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[int] = None
    weight: Optional[float] = None
    rest_seconds: Optional[int] = None
    rir: Optional[int] = None

@dataclass
class PlanSlot:
    order: int
    items: List[PlanItem]

@dataclass
class PlanDay:
    date: str
    name: str
    is_rest: bool = False
    slots: List[PlanSlot] = None
    class_placeholder: bool = False

@dataclass
class Plan:
    routine_name: str
    start_date: str
    end_date: str
    days: List[PlanDay]

# ---------- Parsing ----------
def load_plan(path: str) -> Plan:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict) or "days" not in raw:
        raise ValueError("Plan JSON must be an object with a 'days' array.")
    days: List[PlanDay] = []
    for d in raw.get("days", []):
        slots = []
        for s in d.get("slots", []) or []:
            items = [PlanItem(**i) for i in (s.get("items") or [])]
            slots.append(PlanSlot(order=int(s.get("order", 1)), items=items))
        days.append(PlanDay(
            date=d["date"],
            name=d.get("name",""),
            is_rest=bool(d.get("is_rest", False)),
            slots=slots,
            class_placeholder=bool(d.get("class_placeholder", False))
        ))
    return Plan(
        routine_name=raw.get("routine_name","PeteE. Routine"),
        start_date=raw["start_date"],
        end_date=raw["end_date"],
        days=days
    )

# ---------- Exercise index + name resolution ----------
_punct_re = re.compile(r"[^a-z0-9\s]")

def norm(s: str) -> str:
    s = s.lower()
    s = s.replace("&", " and ")
    s = _punct_re.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

ALIASES = {
    # common barbell names
    "barbell bent over row": ["bent over row","barbell row","bentover row","bent-over row"],
    "barbell overhead press": ["military press","shoulder press","ohp","standing barbell press"],
    # core
    "knee raises": ["hanging knee raise","hanging knee raises","knee raise (hanging)","hanging leg raise (knees bent)"],
}

def fetch_exercise_index(base: str, headers: Dict[str,str], language_id: int = 2) -> List[Dict[str,Any]]:
    """Return a list of exercises with English name + equipment + category."""
    results: List[Dict[str,Any]] = []
    path = "/exerciseinfo/"
    params = {"limit": 100, "offset": 0}
    while True:
        data = GET(base, headers, path, params=params)
        for row in data.get("results", []):
            # english translation if present, else first name we see
            en_name = None
            for tr in row.get("translations", []):
                if tr.get("language") == language_id and tr.get("name"):
                    en_name = tr["name"]
                    break
            if not en_name:
                continue
            eq = [e.get("name","") for e in row.get("equipment", [])]
            cat = (row.get("category") or {}).get("name","")
            results.append({
                "id": row["id"],
                "name": en_name,
                "name_n": norm(en_name),
                "equipment": [norm(x) for x in eq],
                "category": norm(cat)
            })
        next_url = data.get("next")
        if not next_url:
            break
        # Extract next offset safely
        m = re.search(r"offset=(\d+)", next_url)
        if m:
            params["offset"] = int(m.group(1))
        else:
            break
    info(f"[index] Loaded {len(results)} exercises from /exerciseinfo/")
    return results

def alias_candidates(target_n: str) -> List[str]:
    """Return normalized alias candidates for a target name."""
    cands = [target_n]
    for canon, alist in ALIASES.items():
        canon_n = norm(canon)
        if target_n == canon_n or target_n in [norm(a) for a in alist]:
            cands = list({canon_n, *[norm(a) for a in alist], target_n})
    return cands

def score_match(target: str, row: Dict[str,Any], hint_equipment: Optional[str], hint_category: Optional[str]) -> float:
    """Simple token set similarity + small bonuses for equipment/category matches."""
    t_tokens = set(target.split())
    r_tokens = set(row["name_n"].split())
    common = len(t_tokens & r_tokens)
    base = common / max(1, len(t_tokens))
    bonus = 0.0
    if hint_equipment:
        he = norm(hint_equipment)
        bonus += 0.15 if he in row["equipment"] else 0.0
    if hint_category:
        hc = norm(hint_category)
        bonus += 0.10 if hc == row["category"] else 0.0
    return base + bonus

def resolve_exercise_id(name: str, index: List[Dict[str,Any]], hint_equipment: Optional[str], hint_category: Optional[str]) -> Optional[int]:
    t = norm(name)
    candidates = alias_candidates(t)
    best: Tuple[float, Optional[int], str] = (0.0, None, "")
    for cand in candidates:
        for row in index:
            s = score_match(cand, row, hint_equipment, hint_category)
            if s > best[0]:
                best = (s, row["id"], row["name"])
    if best[0] < 0.5:
        return None
    return best[1]

# ---------- Unit helpers ----------
def lookup_unit_id(base: str, headers: Dict[str,str], endpoint: str, target_name: str, fallback: int) -> int:
    try:
        data = GET(base, headers, f"/{endpoint}/")
        for row in data.get("results", []):
            nm = (row.get("name") or row.get("abbreviation") or "").lower()
            if nm == target_name.lower():
                return int(row["id"])
        # if paginated, try simple scan of all pages
        next_url = data.get("next")
        while next_url:
            m = re.search(r"offset=(\d+)", next_url)
            params = {"limit": 100, "offset": int(m.group(1))} if m else {}
            data = GET(base, headers, f"/{endpoint}/", params=params)
            for row in data.get("results", []):
                nm = (row.get("name") or row.get("abbreviation") or "").lower()
                if nm == target_name.lower():
                    return int(row["id"])
            next_url = data.get("next")
    except Exception as e:
        warn(f"Could not look up unit id for {endpoint}='{target_name}': {e}")
    return fallback

# ---------- Builders ----------
def create_routine(base, headers, name: str, dry_run: bool) -> int:
    payload = {"name": name, "is_public": False}
    res = POST(base, headers, "/routine/", payload, dry_run=dry_run)
    rid = int(res["id"])
    info(f"[OK] Created routine id={rid} name={name}")
    return rid

def create_day(base, headers, routine_id: int, order: int, name: str, is_rest: bool, dry_run: bool) -> int:
    payload = {"routine": routine_id, "order": order, "is_rest": bool(is_rest), "name": name}
    res = POST(base, headers, "/day/", payload, dry_run=dry_run)
    did = int(res["id"])
    info(f"  [day] {order} {name} → id={did} is_rest={is_rest}")
    return did

def create_slot(base, headers, day_id: int, order: int, dry_run: bool) -> int:
    payload = {"day": day_id, "order": order}
    res = POST(base, headers, "/slot/", payload, dry_run=dry_run)
    sid = int(res["id"])
    info(f"    [slot] order={order} id={sid}")
    return sid

def create_slot_entry(base, headers, slot_id: int, exercise_id: int, rep_round: Optional[float], weight_round: Optional[float], dry_run: bool) -> int:
    payload = {
        "slot": slot_id,
        "exercise": exercise_id
    }
    # These rounding fields are accepted on the slot-entry object on public server
    if rep_round is not None:   payload["repetition_rounding"] = rep_round
    if weight_round is not None: payload["weight_rounding"]    = weight_round
    res = POST(base, headers, "/slot-entry/", payload, dry_run=dry_run)
    seid = int(res["id"])
    return seid

def post_config_row(base, headers, endpoint: str, slot_id: int, slot_entry_id: int, payload_core: Dict[str,Any], dry_run: bool):
    """
    Some deployments expect the foreign key named 'slot_config' (2.4 docs),
    while the public wger.de often accepts 'slot' on the config rows OR 'slot_config' with the slot-entry id.
    We'll try both, first with slot_config -> slot_entry_id, then with slot -> slot_id.
    """
    for variant in ({"slot_config": slot_entry_id}, {"slot": slot_id}):
        payload = {**variant, **payload_core}
        try:
            POST(base, headers, f"/{endpoint}/", payload, dry_run=dry_run)
            return
        except Exception as e:
            continue
    # If both failed, raise once more with the last variant for visibility
    POST(base, headers, f"/{endpoint}/", {**{"slot": slot_id}, **payload_core}, dry_run=dry_run)

def build_from_plan(plan_path: str, routine_name_override: Optional[str], replace: Optional[str], dry_run: bool):
    base, headers = get_env()
    info(f"[wger] Base URL: {base}")
    info(f"[wger] Dry run: {'YES' if dry_run else 'NO'}")
    info(f"[wger] Reading plan: {plan_path}")

    plan = load_plan(plan_path)
    routine_name = routine_name_override or plan.routine_name

    # Units
    reps_unit_id   = lookup_unit_id(base, headers, "repetition-unit", REPS_UNIT_NAME, fallback=1)
    weight_unit_id = lookup_unit_id(base, headers, "weightunit", WEIGHT_UNIT_NAME, fallback=1)

    # Exercise index (English)
    ex_index = fetch_exercise_index(base, headers, language_id=2)

    # Routine
    rid = create_routine(base, headers, routine_name, dry_run)

    # Days
    for i, d in enumerate(plan.days, start=1):
        did = create_day(base, headers, rid, i, d.name, d.is_rest, dry_run)

        if d.class_placeholder or d.is_rest or not d.slots:
            # no slots to create, continue
            continue

        for s in sorted(d.slots, key=lambda x: x.order):
            sid = create_slot(base, headers, did, s.order, dry_run)

            for item in s.items:
                ex_id = resolve_exercise_id(item.name, ex_index, item.equipment, item.category)
                if not ex_id:
                    warn(f"Could not resolve exercise_id for '{item.name}'. Skipping this item.")
                    continue

                seid = create_slot_entry(base, headers, sid, ex_id, rep_round=1.0, weight_round=0.5, dry_run=dry_run)

                # Default/required numeric configs so the mobile app doesn't choke on nulls
                sets  = int(item.sets  if item.sets  is not None else 3)
                reps  = int(item.reps  if item.reps  is not None else 10)
                rest  = int(item.rest_seconds if item.rest_seconds is not None else 90)
                rir   = int(item.rir   if item.rir   is not None else 2)

                # Config rows:
                post_config_row(base, headers, "sets-config", sid, seid, {"value": sets}, dry_run)
                post_config_row(base, headers, "repetitions-config", sid, seid, {"value": reps, "unit": reps_unit_id}, dry_run)
                if item.weight is not None:
                    post_config_row(base, headers, "weight-config", sid, seid, {"value": float(item.weight), "unit": weight_unit_id}, dry_run)
                # Always provide rest and RIR
                post_config_row(base, headers, "rest-config", sid, seid, {"value": rest}, dry_run)
                post_config_row(base, headers, "rir-config", sid, seid, {"value": rir}, dry_run)

    info("[DONE] Plan applied.")

# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser(description="Apply a 4‑week plan to WGER as a routine")
    ap.add_argument("plan", help="Path to plan JSON")
    ap.add_argument("--dry-run", action="store_true", help="Do not POST, just log actions")
    ap.add_argument("--replace-days", default=None, help="(reserved) replace rules")
    ap.add_argument("--routine-name", default=None, help="Override routine name")
    args = ap.parse_args()
    build_from_plan(args.plan, routine_name_override=args.routine_name, replace=args.replace_days, dry_run=args.dry_run)

if __name__ == "__main__":
    main()