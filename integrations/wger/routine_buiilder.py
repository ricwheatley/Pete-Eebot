#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apply a plan JSON to Wger Routine API (upsert by name).
Resolves exercise IDs by name using cached catalog or live /exerciseinfo/ if missing.

Usage:
  python integrations/wger/routine_builder.py --plan path.json [--replace-days] [--dry-run]

Env:
  WGER_API_KEY (required)
  WGER_BASE_URL (optional, default https://wger.de/api/v2)
"""
import argparse, json, os, sys, requests
from typing import Any, Dict, List, Optional

BASE = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").strip().rstrip("/")
API_KEY = os.environ.get("WGER_API_KEY")

HEADERS = {
    "Authorization": f"Token {API_KEY}" if API_KEY else "",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

STATE_DIR = "integrations/wger/state"
CATALOG_JSON = "integrations/wger/catalog/exercises_en.json"

def die(msg: str, code: int = 1) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr); sys.exit(code)

def check_env() -> None:
    if not API_KEY: die("WGER_API_KEY is not set.")

def req(method: str, url: str, *, params: Optional[Dict[str, Any]]=None, payload: Optional[Dict[str, Any]]=None) -> requests.Response:
    r = requests.request(method.upper(), url, headers=HEADERS, params=params, json=payload, timeout=60)
    if not r.ok:
        print(f"{method} {url} -> {r.status_code}: {r.text[:800]}", file=sys.stderr)
    r.raise_for_status(); return r

def get(url: str, params: Optional[Dict[str, Any]]=None) -> requests.Response: return req("GET", url, params=params)
def post(url: str, payload: Dict[str, Any]) -> requests.Response: return req("POST", url, payload=payload)
def patch(url: str, payload: Dict[str, Any]) -> requests.Response: return req("PATCH", url, payload=payload)
def delete(url: str) -> None:
    r = requests.delete(url, headers=HEADERS, timeout=60)
    if r.status_code not in (200,202,204):
        print(f"[WARN] DELETE {url} => {r.status_code}: {r.text[:300]}", file=sys.stderr)

# ---------- Exercise ID resolution ----------
def load_catalog() -> List[Dict[str, Any]]:
    if os.path.exists(CATALOG_JSON):
        try:
            with open(CATALOG_JSON, "r", encoding="utf-8") as f: return json.load(f)
        except Exception:
            pass
    return []

def fetch_all_exerciseinfo() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    next_url = f"{BASE}/exerciseinfo/"
    while next_url:
        r = requests.get(next_url, timeout=60)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "results" in data:
            results.extend(data["results"])
            next_url = data.get("next")
        elif isinstance(data, list):
            results.extend(data); next_url = None
        else:
            break
    return results

def normalize_name(s: str) -> str:
    return (s or "").lower().strip()

def build_index(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    idx = {}
    for ex in rows:
        name = ""
        # Prefer english translation if present
        trans = ex.get("translations") or []
        en = None
        for t in trans:
            if t.get("language") == 2 and t.get("name"):
                en = t; break
        name = (en.get("name") if en else ex.get("name") or "").strip() if (en or ex.get("name")) else ""
        if name:
            idx[normalize_name(name)] = ex.get("id")
    return idx

def resolve_exercise_ids(plan: Dict[str, Any]) -> None:
    # Load catalog if available; else fetch live
    cat = load_catalog()
    if not cat:
        try:
            info = fetch_all_exerciseinfo()
        except Exception:
            info = []
        # adapt to exerciseinfo structure
        # ensure we can index by english translation
        ex_index = build_index(info)
    else:
        # catalog already simplified to english fields
        ex_index = {normalize_name(row.get("name")): row.get("id") for row in cat if row.get("name")}
    # Walk days and fill exercise_id if missing
    for d in plan.get("days", []):
        for ex in d.get("exercises", []) or []:
            if ex.get("exercise_id"):
                continue
            name = normalize_name(ex.get("name"))
            if name in ex_index:
                ex["exercise_id"] = ex_index[name]
            else:
                # try a contains match
                matches = [k for k in ex_index.keys() if all(tok in k for tok in name.split())]
                if matches:
                    ex["exercise_id"] = ex_index[matches[0]]
                else:
                    print(f"[WARN] Could not resolve exercise_id for '{ex.get('name')}'.", file=sys.stderr)

# ---------- Routine upsert & build ----------
def find_routine_by_name(name: str) -> Optional[Dict[str, Any]]:
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
        payload = {"name": name, "start": rdata.get("start"), "end": rdata.get("end"),
                   "fit_in_week": rdata.get("fit_in_week", True),
                   "description": rdata.get("description", "")}
        res = patch(f"{BASE}/routine/{rid}/", payload).json()
        print(f"[OK] Updated existing routine id={rid} name={name}")
        return res
    else:
        rdata = rdata.copy(); rdata["name"] = name[:25]  # conservative limit
        res = post(f"{BASE}/routine/", rdata).json()
        print(f"[OK] Created routine id={res.get('id')} name={res.get('name')}")
        return res

def list_days(routine_id: int) -> List[Dict[str, Any]]:
    res = get(f"{BASE}/day/", params={"routine": routine_id, "limit": 200}).json()
    return res.get("results", []) if isinstance(res, dict) else res

def replace_days(routine_id: int) -> None:
    for d in list_days(routine_id):
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
    payload: Dict[str, Any] = {"slot_config": slot_config_id, "iterations": iteration, "operation": operation, "value": value, "step": step}
    if requirements: payload["requirements"] = requirements
    if repeat is not None: payload["repeat"] = bool(repeat)
    return post(f"{BASE}/{endpoint}/", payload).json()

def apply_exercise_settings(slot_config_id: int, ex: Dict[str, Any]) -> None:
    sets_val = ex.get("sets")
    if sets_val: create_prop_config("sets-config", slot_config_id, 1, "r", float(sets_val), step="abs")
    reps = ex.get("reps")
    if reps:
        if isinstance(reps, str) and "-" in reps:
            lo, hi = reps.split("-", 1)
            create_prop_config("repetitions-config", slot_config_id, 1, "r", float(lo), step="abs")
            create_prop_config("max-repetitions-config", slot_config_id, 1, "r", float(hi), step="abs")
        else:
            create_prop_config("repetitions-config", slot_config_id, 1, "r", float(reps), step="abs")
    rir = ex.get("rir")
    if rir is not None: create_prop_config("rir-config", slot_config_id, 1, "r", float(rir), step="abs")
    rest_s = ex.get("rest_s")
    if rest_s is not None: create_prop_config("rest-config", slot_config_id, 1, "r", float(rest_s), step="abs")
    weight_kg = ex.get("weight_kg")
    if weight_kg is not None: create_prop_config("weight-config", slot_config_id, 1, "r", float(weight_kg), step="abs")
    prog = ex.get("progression") or {}
    wprog = prog.get("weight")
    if isinstance(wprog, dict):
        inc = float(wprog.get("each_iteration_percent", 0))
        iters = wprog.get("iterations") or []
        req = wprog.get("requirements")
        for it in iters:
            create_prop_config("weight-config", slot_config_id, int(it), "+", inc, step="percent", requirements=req)
    # Week-4 deload of sets if provided
    deload_sets = prog.get("deload_sets")
    if deload_sets is not None:
        try:
            ds = float(deload_sets)
            create_prop_config("sets-config", slot_config_id, 4, "r", ds, step="abs")
        except Exception:
            pass

def build_from_plan(plan_path: str, replace: bool, routine_name_override: Optional[str], dry_run: bool = False) -> Dict[str, Any]:
    with open(plan_path, "r", encoding="utf-8") as f: plan = json.load(f)
    if dry_run: print(f"[DRY-RUN] Would upsert routine & days from {plan_path}"); return {}
    # Resolve exercise IDs by name if missing
    resolve_exercise_ids(plan)
    # Upsert routine
    rdata = plan.get("routine") or {}
    r = upsert_routine(rdata, routine_name_override)
    rid = r["id"]
    if replace: replace_days(rid)
    # Build days and slots
    for d in plan.get("days", []):
        dres = create_day(rid, d); day_id = dres["id"]
        print(f"  [day] {dres.get('order')} {dres.get('name')} → id={day_id} is_rest={dres.get('is_rest')}")
        exs = d.get("exercises") or []
        # Group by superset_id (None => own slot)
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for idx, ex in enumerate(exs, start=1):
            key = str(ex.get("superset_id")) if ex.get("superset_id") is not None else f"__single_{idx}"
            buckets.setdefault(key, []).append(ex)
        slot_order = 1
        for key, items in buckets.items():
            slot = create_slot(day_id, slot_order, "normal"); slot_id = slot["id"]
            print(f"    [slot] order={slot_order} id={slot_id} items={len(items)}"); slot_order += 1
            for e in items:
                ex_id = e.get("exercise_id")
                if not ex_id:
                    print(f"      [WARN] Missing exercise_id for '{e.get('name')}', skipping.", file=sys.stderr); continue
                sc = create_slotconfig(slot_id, ex_id, rep_round=None, weight_round=0.5); sc_id = sc["id"]
                print(f"      [slotconfig] id={sc_id} ex_id={ex_id} name={e.get('name')}")
                apply_exercise_settings(sc_id, e)
    # State
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "last_routine.json"), "w", encoding="utf-8") as sf:
        json.dump({"routine_id": rid, "plan_path": plan_path, "routine_name": r.get("name")}, sf, ensure_ascii=False, indent=2)
    return r

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--replace-days", action="store_true")
    ap.add_argument("--routine-name", type=str, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    check_env()
    build_from_plan(args.plan, replace=args.replace_days, routine_name_override=args.routine_name, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
