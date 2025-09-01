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

# Cache exercise names from /exerciseinfo/<id> (English translation preferred)
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

def pick_iter(rows: List[Dict[str,Any]], it=1) -> Optional[Dict[str,Any]]:
    if not rows: return None
    # Try to pick iteration==1; otherwise the first
    rows1 = [r for r in rows if int(r.get("iteration", 0)) == it]
    return rows1[0] if rows1 else rows[0]

def cfg(path: str, slot_entry_id: int) -> Optional[int]:
    res = GET(f"{path}?slot_entry={slot_entry_id}&limit=50").get("results", [])
    row = pick_iter(res, 1)
    return int(row["value"]) if row and "value" in row else None

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
                seid = e["id"]; ex_id = int(e["exercise"]); exn = exercise_name(ex_id)
                sets = cfg("/sets-config/", seid)
                reps = cfg("/repetitions-config/", seid); reps_max = cfg("/max-repetitions-config/", seid)
                weight = cfg("/weight-config/", seid)
                rir = cfg("/rir-config/", seid)
                rest = cfg("/rest-config/", seid)
                reps_str = f"{reps}-{reps_max}" if reps and reps_max and reps_max!=reps else (str(reps) if reps else "-")
                print(f"    • {exn} (ex={ex_id})  sets={sets or '-'} reps={reps_str} wt={weight or '-'} RIR={rir or '-'} rest={rest or '-'}s")

if __name__ == "__main__":
    rid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not rid:
        print("Usage: python integrations/wger/routine_inspect.py <routine_id>")
        sys.exit(2)
    summarize_routine(rid)