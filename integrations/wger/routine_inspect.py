#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, requests
from typing import Dict, Any, List, Optional

BASE = (os.environ.get("WGER_BASE_URL") or "https://wger.de/api/v2").rstrip("/")
API_KEY = (os.environ.get("WGER_API_KEY") or "").strip()
HDRS = {"Accept":"application/json","Content-Type":"application/json"}
if API_KEY: HDRS["Authorization"] = f"Token {API_KEY}"

def req(method: str, url: str, params=None, ok=(200,), tries=2, backoff=0.5):
    last = None
    for i in range(tries):
        r = requests.request(method, url, headers=HDRS, params=params, timeout=60)
        if r.status_code in ok: return r
        last = r
        if 500 <= r.status_code < 600 and i < tries-1:
            time.sleep(backoff); continue
        r.raise_for_status()
    last.raise_for_status(); return last

def GET(p: str, params=None):
    url = p if p.startswith("http") else f"{BASE}{p}"
    return req("GET", url, params=params, ok=(200,)).json()

# ---------- helpers for numeric parsing & printing ----------

def parse_num(v: Any) -> Optional[float]:
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s: return None
        try: return float(s)
        except: return None
    return None

def fmt_num(x: Optional[float]) -> str:
    if x is None: return "-"
    # show integer cleanly, else trim trailing zeros
    if abs(x - round(x)) < 1e-9: return str(int(round(x)))
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s

# ---------- basic fetchers ----------

def get_days(routine_id: int) -> List[Dict[str,Any]]:
    out, url = [], f"/day/?routine={routine_id}&limit=100"
    while url:
        page = GET(url)
        out += page.get("results", [])
        url = page.get("next") or ""
    out.sort(key=lambda d: d.get("order", 0))
    return out

def get_slots(day_id: int) -> List[Dict[str,Any]]:
    out, url = [], f"/slot/?day={day_id}&limit=100"
    while url:
        page = GET(url)
        out += page.get("results", [])
        url = page.get("next") or ""
    out.sort(key=lambda s: s.get("order", 0))
    return out

def get_slot_entries(slot_id: int) -> List[Dict[str,Any]]:
    out, url = [], f"/slot-entry/?slot={slot_id}&limit=100"
    while url:
        page = GET(url)
        out += page.get("results", [])
        url = page.get("next") or ""
    out.sort(key=lambda e: e.get("order", 0))
    return out

# ---------- exercise names ----------

EX_NAME_CACHE: Dict[int,str] = {}
def exercise_name(ex_id: int) -> str:
    if ex_id in EX_NAME_CACHE: return EX_NAME_CACHE[ex_id]
    row = GET(f"/exerciseinfo/{ex_id}/")
    name = None
    for tr in row.get("translations", []):
        if tr.get("language") == 2 and tr.get("name"):
            name = tr["name"]; break
    name = name or row.get("name") or f"Exercise {ex_id}"
    EX_NAME_CACHE[ex_id] = name
    return name

# ---------- configs (prefer slot_entry; fallback slot_config) ----------

def pick_iter(rows: List[Dict[str,Any]], it=1) -> Optional[Dict[str,Any]]:
    if not rows: return None
    rows1 = [r for r in rows if int(r.get("iteration", 0)) == it]
    return rows1[0] if rows1 else rows[0]

def find_slotconfig_id(slot_id: int, exercise_id: int) -> Optional[int]:
    res = GET(f"/slotconfig/?slot={slot_id}&exercise={exercise_id}&limit=5").get("results", [])
    return int(res[0]["id"]) if res else None

def cfg_for_slot_entry(path: str, slot_entry_id: int) -> Optional[float]:
    res = GET(f"{path}?slot_entry={slot_entry_id}&limit=50").get("results", [])
    row = pick_iter(res, 1)
    return parse_num(row.get("value")) if row else None

def cfg_for_slot_config(path: str, slot_config_id: int) -> Optional[float]:
    res = GET(f"{path}?slot_config={slot_config_id}&limit=50").get("results", [])
    row = pick_iter(res, 1)
    return parse_num(row.get("value")) if row else None

def summarize_routine(routine_id: int):
    print(f"[inspect] routine_id={routine_id} @ {BASE}")
    days = get_days(routine_id)
    for d in days:
        did = d["id"]; name = d.get("name") or f"Day {d.get('order',0)}"
        is_rest = bool(d.get("is_rest", False))
        print(f"\nDAY {d.get('order',0)} — {name}  (rest={is_rest})")
        if is_rest: continue
        slots = get_slots(did)
        for s in slots:
            sid = s["id"]; order = s.get("order",0)
            entries = get_slot_entries(sid)
            superset = " (SUPERSET)" if len(entries) > 1 else ""
            print(f"  Slot {order} id={sid}{superset}")
            for e in entries:
                seid = int(e["id"])
                ex_id = int(e["exercise"])
                exn = exercise_name(ex_id)

                # configs from slot_entry; if missing, try slot_config
                sets = cfg_for_slot_entry("/sets-config/", seid)
                reps_lo = cfg_for_slot_entry("/repetitions-config/", seid)
                reps_hi = cfg_for_slot_entry("/max-repetitions-config/", seid)
                weight  = cfg_for_slot_entry("/weight-config/", seid)
                rir     = cfg_for_slot_entry("/rir-config/", seid)
                rest    = cfg_for_slot_entry("/rest-config/", seid)

                if all(v is None for v in (sets, reps_lo, reps_hi, weight, rir, rest)):
                    scid = find_slotconfig_id(sid, ex_id)
                    if scid:
                        sets = sets or cfg_for_slot_config("/sets-config/", scid)
                        reps_lo = reps_lo or cfg_for_slot_config("/repetitions-config/", scid)
                        reps_hi = reps_hi or cfg_for_slot_config("/max-repetitions-config/", scid)
                        weight  = weight  or cfg_for_slot_config("/weight-config/", scid)
                        rir     = rir     or cfg_for_slot_config("/rir-config/", scid)
                        rest    = rest    or cfg_for_slot_config("/rest-config/", scid)

                reps_str = "-"
                if reps_lo is not None:
                    if reps_hi is not None and abs((reps_hi)-(reps_lo)) > 1e-9:
                        reps_str = f"{fmt_num(reps_lo)}-{fmt_num(reps_hi)}"
                    else:
                        reps_str = fmt_num(reps_lo)

                print(f"    • {exn} (ex={ex_id})  sets={fmt_num(sets)} reps={reps_str} wt={fmt_num(weight)} RIR={fmt_num(rir)} rest={fmt_num(rest)}s")

if __name__ == "__main__":
    rid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not rid:
        print("Usage: python integrations/wger/routine_inspect.py <routine_id>")
        sys.exit(2)
    summarize_routine(rid)