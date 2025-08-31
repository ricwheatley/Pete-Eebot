#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build a full Wger Routine (routine -> days -> slots -> slotconfigs -> configs)
from a plan JSON file created by plan_next_block.py (or compatible).

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

def post(url: str, payload: Dict[str, Any]) -> requests.Response:
    r = requests.post(url, headers=HEADERS, json=payload, timeout=60)
    try:
        r.raise_for_status()
    except Exception:
        # print helpful content
        print(f"Request failed ({r.status_code}) for {url}: {r.text[:800]}", file=sys.stderr)
        raise
    return r

def get(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    r = requests.get(url, headers=HEADERS, params=params, timeout=60)
    r.raise_for_status()
    return r

def delete(url: str) -> None:
    r = requests.delete(url, headers=HEADERS, timeout=60)
    if r.status_code not in (200, 202, 204):
        print(f"[WARN] DELETE {url} => {r.status_code}: {r.text[:300]}", file=sys.stderr)

def create_routine(plan: Dict[str, Any], routine_name_override: Optional[str]) -> Dict[str, Any]:
    rdata = plan["routine"].copy()
    if routine_name_override:
        rdata["name"] = routine_name_override
    url = f"{BASE}/routine/"
    res = post(url, rdata).json()
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
        "name": d.get("name")[:50],
        "type": d.get("type", "custom"),
        "description": d.get("description", "")[:1000],
        "is_rest": bool(d.get("is_rest", False)),
        "need_logs_to_advance": bool(d.get("need_logs_to_advance", False)),
    }
    return post(f"{BASE}/day/", payload).json()

def create_slot(day_id: int, order: int, stype: str = "normal") -> Dict[str, Any]:
    payload = {
        "day": day_id,
        "order": order,
        "type": stype,
    }
    return post(f"{BASE}/slot/", payload).json()

def create_slotconfig(slot_id: int, exercise_id: int, rep_round: Optional[float] = None, weight_round: Optional[float] = None) -> Dict[str, Any]:
    payload = {
        "slot": slot_id,
        "exercise": exercise_id,
    }
    if rep_round is not None:
        payload["repetition_rounding"] = rep_round
    if weight_round is not None:
        payload["weight_rounding"] = weight_round
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

    # reps (handle range "6-8")
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

    # Progression (optional)
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

    if dry_run:
        print(f"[DRY-RUN] Would create routine & days from {plan_path}")
        return {}

    # Routine
    r = create_routine(plan, routine_name_override)
    rid = r["id"]
    print(f"[OK] Created routine id={rid} name={r.get('name')}")

    # Days
    if replace:
        replace_days(rid)

    # Build days and exercises
    for d in plan.get("days", []):
        dres = create_day(rid, d)
        day_id = dres["id"]
        print(f"  [day] {dres.get('order')} {dres.get('name')} → id={day_id} is_rest={dres.get('is_rest')}")

        # Group exercises into slots by superset_id (None => one exercise per slot)
        exs = d.get("exercises") or []
        # Build a mapping superset_id -> list of exercises
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
    state = {"routine_id": rid, "plan_path": plan_path}
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
