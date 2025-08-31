#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build a full Wger Routine (routine -> days -> slots -> slotconfigs -> configs)
from a plan JSON file created by plan_next_block.py (or compatible).

Idempotent: if a routine with the same name already exists, we PATCH it and (optionally) replace days.

Usage:
  python integrations/wger/routine_builder.py --plan integrations/wger/plans/plan_YYYY-MM-DD_YYYY-MM-DD.json [--replace-days] [--dry-run]

Environment:
  WGER_API_KEY  (required)
  WGER_BASE_URL (optional, default https://wger.de/api/v2)

It writes state to: integrations/wger/state/last_routine.json
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional
import requests

BASE = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").strip().rstrip("/")
API_KEY = os.environ.get("WGER_API_KEY")

HEADERS = {
    "Authorization": f"Token {API_KEY}" if API_KEY else "",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

STATE_DIR = "integrations/wger/state"

def die(msg: str, code: int = 1) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(code)

def check_env() -> None:
    if not API_KEY:
        die("WGER_API_KEY is not set")

def req(method: str, url: str, *, params: Optional[Dict[str, Any]] = None, payload: Optional[Dict[str, Any]] = None) -> requests.Response:
    r = requests.request(method=method.upper(), url=url, headers=HEADERS, params=params, json=payload, timeout=60)
    if not r.ok:
        print(f"{method} {url} -> {r.status_code}: {r.text[:800]}", file=sys.stderr)
    r.raise_for_status()
    return r

def get(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    return req("GET", url, params=params)

def post(url: str, payload: Dict[str, Any]) -> requests.Response:
    return req("POST", url, payload=payload)

def patch(url: str, payload: Dict[str, Any]) -> requests.Response:
    return req("PATCH", url, payload=payload)

def delete(url: str) -> None:
    r = requests.delete(url, headers=HEADERS, timeout=60)
    if r.status_code not in (200, 202, 204):
        print(f"[WARN] DELETE {url} => {r.status_code}: {r.text[:300]}", file=sys.stderr)

def find_routine_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Return an exact-name match if found, else None."""
    res = get(f"{BASE}/routine/", params={"search": name, "limit": 50}).json()
    items = res.get("results", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
    for it in items:
        if (it.get("name") or "") == name:
            return it
    return None

def upsert_routine(rdata: Dict[str, Any], name_override: Optional[str]) -> Dict[str, Any]:
    name = name_override or rdata.get("name") or "Routine"
    existing = find_routine_by_name(name)
    if existing:
        rid = existing["id"]
        payload = {
            "name": name,
            "start": rdata.get("start"),
            "end": rdata.get("end"),
            "fit_in_week": rdata.get("fit_in_week", True),
            "description": rdata.get("description", ""),
        }
        res = patch(f"{BASE}/routine/{rid}/", payload).json()
        print(f"[OK] Updated existing routine id={rid} name={name}")
        return res
    else:
        rdata = rdata.copy()
        rdata["name"] = name[:25]  # enforce conservative length
        res = post(f"{BASE}/routine/", rdata).json()
        print(f"[OK] Created routine id={res.get('id')} name={res.get('name')}")
        return res

def list_days(routine_id: int) -> List[Dict[str, Any]]:
    res = get(f"{BASE}/day/", params={"routine": routine_id, "limit": 200}).json()
    return res.get("results", []) if isinstance(res, dict) else res

def replace_days(routine_id: int) -> None:
    days = list_days(routine_id)
    for d in days:
        delete(f"{BASE}/day/{d['id']}/")

def create_day(routine_id: int, d: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "routine": routine_id,
        "order": d["order"],
        "name": (d.get("name") or "Day")[:20],
        "type": d.get("type", "custom"),
        "description": (d.get("description") or "")[:1000],
        "is_rest": bool(d.get("is_rest", False)),
        "need_logs_to_advance": bool(d.get("need_logs_to_advance", False)),
    }
    return post(f"{BASE}/day/", payload).json()

def create_slot(day_id: int, order: int, stype: str = "normal") -> Dict[str, Any]:
    payload = {"day": day_id, "order": order, "type": stype}
    return post(f"{BASE}/slot/", payload).json()

def create_slotconfig(slot_id: int, exercise_id: int, rep_round: Optional[float] = None, weight_round: Optional[float] = None) -> Dict[str, Any]:
    payload = {"slot": slot_id, "exercise": exercise_id}
    if rep_round is not None: payload["repetition_rounding"] = rep_round
    if weight_round is not None: payload["weight_rounding"] = weight_round
    return post(f"{BASE}/slotconfig/", payload).json()

def create_prop_config(endpoint: str, slot_config_id: int, iteration: int, operation: str, value: float, step: str = "abs", requirements: Optional[Dict[str, Any]] = None, repeat: Optional[bool] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "slot_config": slot_config_id,
        "iterations": iteration,
        "operation": operation,  # 'r' replace | '+' | '-'
        "value": value,
        "step": step,            # 'abs' or 'percent'
    }
    if requirements:
        payload["requirements"] = requirements
    if repeat is not None:
        payload["repeat"] = bool(repeat)
    return post(f"{BASE}/{endpoint}/", payload).json()

def apply_exercise_settings(slot_config_id: int, ex: Dict[str, Any]) -> None:
    # sets
    sets_val = ex.get("sets")
    if sets_val:
        create_prop_config("sets-config", slot_config_id, 1, "r", float(sets_val), step="abs")
    # reps (range supported via max-repetitions-config)
    reps = ex.get("reps")
    if reps:
        if isinstance(reps, str) and "-" in reps:
            lo, hi = reps.split("-", 1)
            create_prop_config("repetitions-config", slot_config_id, 1, "r", float(lo), step="abs")
            create_prop_config("max-repetitions-config", slot_config_id, 1, "r", float(hi), step="abs")
        else:
            create_prop_config("repetitions-config", slot_config_id, 1, "r", float(reps), step="abs")
    # RIR
    rir = ex.get("rir")
    if rir is not None:
        create_prop_config("rir-config", slot_config_id, 1, "r", float(rir), step="abs")
    # Rest seconds
    rest_s = ex.get("rest_s")
    if rest_s is not None:
        create_prop_config("rest-config", slot_config_id, 1, "r", float(rest_s), step="abs")
    # Base weight (optional)
    weight_kg = ex.get("weight_kg")
    if weight_kg is not None:
        create_prop_config("weight-config", slot_config_id, 1, "r", float(weight_kg), step="abs")
    # Progression (optional): percent increases on iterations 2..N
    prog = ex.get("progression") or {}
    wprog = prog.get("weight")
    if isinstance(wprog, dict):
        inc = float(wprog.get("each_iteration_percent", 0))
        iters = wprog.get("iterations") or []
        req = wprog.get("requirements")
        for it in iters:
            create_prop_config("weight-config", slot_config_id, int(it), "+", inc, step="percent", requirements=req)

def build_from_plan(plan_path: str, replace: bool, routine_name_override: Optional[str], dry_run: bool = False) -> Dict[str, Any]:
    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    rdata = plan.get("routine") or {}
    if dry_run:
        print(f"[DRY-RUN] Would upsert routine & days from {plan_path}")
        return {}

    # Upsert routine (by name)
    r = upsert_routine(rdata, routine_name_override)
    rid = r["id"]

    # Days: replace or append
    if replace:
        replace_days(rid)

    for d in plan.get("days", []):
        dres = create_day(rid, d)
        day_id = dres["id"]
        print(f"  [day] {dres.get('order')} {dres.get('name')} → id={day_id} is_rest={dres.get('is_rest')}")

        # Group exercises into slots by superset_id
        exs = d.get("exercises") or []
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for idx, ex in enumerate(exs, start=1):
            key = str(ex.get("superset_id")) if ex.get("superset_id") is not None else f"__single_{idx}"
            buckets.setdefault(key, []).append(ex)

        slot_order = 1
        for key, items in buckets.items():
            slot = create_slot(day_id, slot_order, "normal")
            slot_id = slot["id"]
            print(f"    [slot] order={slot_order} id={slot_id} items={len(items)}")
            slot_order += 1

            for e in items:
                ex_id = e.get("exercise_id")
                if not ex_id:
                    print(f"      [WARN] Missing exercise_id for '{e.get('name')}', skipping slotconfig.", file=sys.stderr)
                    continue
                sc = create_slotconfig(slot_id, ex_id, rep_round=None, weight_round=0.5)
                sc_id = sc["id"]
                print(f"      [slotconfig] id={sc_id} exercise_id={ex_id}")
                apply_exercise_settings(sc_id, e)

    # State
    os.makedirs(STATE_DIR, exist_ok=True)
    state = {"routine_id": rid, "plan_path": plan_path, "routine_name": r.get("name")}
    with open(os.path.join(STATE_DIR, "last_routine.json"), "w", encoding="utf-8") as sf:
        json.dump(state, sf, ensure_ascii=False, indent=2)

    return r

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, help="Path to plan JSON")
    ap.add_argument("--replace-days", action="store_true")
    ap.add_argument("--routine-name", type=str, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    check_env()
    build_from_plan(args.plan, replace=args.replace_days, routine_name_override=args.routine_name, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
