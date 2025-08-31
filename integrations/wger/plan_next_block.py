#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate a proposed 4-week plan (routine + days + exercises) as JSON.

- Uses an anchor start date to align 4-week blocks (default 2025-09-01, Monday).
- Schedules Weights on Mon/Wed, Blaze (HIIT) on Tue/Thu/Sat, Mobility/Rest Fri, Rest Sun.
- Pulls exercise IDs from the cached catalog (integrations/wger/catalog/exercises_en.json).
- Emits plan JSON to integrations/wger/plans/plan_<start>_<end>.json
- Writes a small state file at integrations/wger/state/last_proposal.json

You can override start date or number of weeks.
"""
import argparse
import datetime as dt
import json
import os
import sys
from typing import Dict, Any, List, Optional

CATALOG_JSON = "integrations/wger/catalog/exercises_en.json"
OUT_DIR = "integrations/wger/plans"
STATE_DIR = "integrations/wger/state"

ANCHOR_START = dt.date(2025, 9, 1)  # Monday, as per project brief

# Blaze class times (Mon..Sun) for description only
BLAZE_TIMES = {
    0: "06:15",  # Mon
    1: "07:00",  # Tue
    2: "07:00",  # Wed
    3: "06:15",  # Thu
    4: "06:15",  # Fri
    5: "08:00",  # Sat
    6: "09:05",  # Sun
}

# ---------- Helpers ----------

def next_block_start(today: dt.date, anchor: dt.date) -> dt.date:
    """Return the next Monday that aligns with the 4-week cadence from anchor."""
    # Find next Monday
    days_ahead = (0 - today.weekday()) % 7  # Monday=0
    candidate = today + dt.timedelta(days=days_ahead)
    # Align to 4-week (28-day) cadence from anchor
    delta_days = (candidate - anchor).days
    mod = delta_days % 28
    if mod != 0:
        candidate += dt.timedelta(days=(28 - mod))
    return candidate

def get_block_end(start: dt.date, weeks: int) -> dt.date:
    return start + dt.timedelta(days=7*weeks - 1)

def read_catalog(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        print(f"[WARN] Catalog not found at {path}. Run catalog_refresh.py first.", file=sys.stderr)
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def find_exercise_id(catalog: List[Dict[str, Any]], want: str) -> Optional[int]:
    want_l = want.lower().strip()
    # Exact case-insensitive first
    for row in catalog:
        if (row.get("name") or "").lower().strip() == want_l:
            return row.get("id")
    # Contains search fallback
    best = None
    for row in catalog:
        n = (row.get("name") or "").lower()
        if all(tok in n for tok in want_l.split()):
            best = row.get("id")
            break
    return best

def resolve_ids(catalog: List[Dict[str, Any]], names: List[str]) -> Dict[str, Optional[int]]:
    return {name: find_exercise_id(catalog, name) for name in names}

# ---------- Defaults (Phase 1 Lower/Upper + Blaze) ----------

LOWER = [
    ("Barbell Squat",                   4, "5",   2, 180, None),
    ("Romanian Deadlift",              3, "8",   2, 150, None),
    ("Leg Press",                      3, "10",  1, 120, None),
    # Superset A (use same superset_id)
    ("Standing Calf Raise",            3, "12",  1, 90,  "A"),
    ("Hanging Knee Raise",             3, "12",  1, 60,  "A"),
]

UPPER = [
    ("Barbell Bench Press",            4, "5",   2, 180, None),
    ("Barbell Bent-Over Row",          3, "8",   2, 150, None),
    ("Barbell Overhead Press",         3, "6",   2, 150, None),
    # Superset B
    ("Lat Pulldown",                   3, "10",  1, 90,  "B"),
    ("Seated Cable Row",               3, "10",  1, 90,  "B"),
    ("Face Pull",                      3, "12",  1, 60,  None),
]

def make_day(day_order: int, name: str, d_type: str, is_rest: bool, description: str, exercises: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "order": day_order,
        "name": name,
        "type": d_type,
        "is_rest": is_rest,
        "need_logs_to_advance": True if not is_rest else False,
        "description": description,
        "exercises": exercises,
    }

def exercise_entry(ex_id: Optional[int], name: str, sets: int, reps: str, rir: int, rest_s: int, superset_id: Optional[str]) -> Dict[str, Any]:
    e: Dict[str, Any] = {
        "exercise_id": ex_id,
        "name": name,
        "sets": sets,
        "reps": reps,  # can be "8" or "6-8"
        "rir": rir,
        "rest_s": rest_s,
        "superset_id": superset_id,
        # Optional progression – applied by routine_builder if present
        "progression": {
            "weight": {"each_iteration_percent": 2.5, "iterations": [2,3,4], "requirements": {"rules": ["weight", "repetitions"]}},
        }
    }
    return e

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", type=str, help="YYYY-MM-DD; if omitted compute next 4-week boundary")
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--out-dir", type=str, default=OUT_DIR)
    args = ap.parse_args()

    today = dt.date.today()
    if args.start_date:
        start = dt.date.fromisoformat(args.start_date)
    else:
        start = next_block_start(today, ANCHOR_START)
    end = get_block_end(start, args.weeks)

    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)

    catalog = read_catalog(CATALOG_JSON)

    lower_names = [x[0] for x in LOWER]
    upper_names = [x[0] for x in UPPER]
    resolved = resolve_ids(catalog, list(set(lower_names + upper_names)))
    # Build exercise lists with IDs
    lower_exercises = [
        exercise_entry(resolved.get(n), n, s, r, rir, rest, sup)
        for (n, s, r, rir, rest, sup) in LOWER
    ]
    upper_exercises = [
        exercise_entry(resolved.get(n), n, s, r, rir, rest, sup)
        for (n, s, r, rir, rest, sup) in UPPER
    ]

    # Days Mon..Sun
    days: List[Dict[str, Any]] = []
    # 1 Mon Lower
    days.append(make_day(1, "Lower", "custom", False, "Weights — Lower body", lower_exercises))
    # 2 Tue Blaze
    days.append(make_day(2, "Blaze", "hiit", False, f"Blaze HIIT @ {BLAZE_TIMES[1]} (45 min).", []))
    # 3 Wed Upper
    days.append(make_day(3, "Upper", "custom", False, "Weights — Upper body", upper_exercises))
    # 4 Thu Blaze
    days.append(make_day(4, "Blaze", "hiit", False, f"Blaze HIIT @ {BLAZE_TIMES[3]} (45 min).", []))
    # 5 Fri Mobility / Rest
    days.append(make_day(5, "Mobility & Steps", "custom", True, "Active recovery, mobility and 10k steps.", []))
    # 6 Sat Blaze
    days.append(make_day(6, "Blaze", "hiit", False, f"Blaze HIIT @ {BLAZE_TIMES[5]} (45 min).", []))
    # 7 Sun Rest (optionally Blaze @ 09:05 if attending)
    days.append(make_day(7, "Rest / Optional Blaze", "hiit", True, f"Optional Blaze @ {BLAZE_TIMES[6]}; otherwise rest + mobility.", []))

    plan = {
        "routine": {
            "name": f"PeteE Block {start.isoformat()}–{end.isoformat()}",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "fit_in_week": True,
            "description": "4-week Lower/Upper + Blaze plan generated automatically",
        },
        "days": days,
    }

    out_path = os.path.join(args.out_dir, f"plan_{start.isoformat()}_{end.isoformat()}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    # Store proposal state
    with open(os.path.join(STATE_DIR, "last_proposal.json"), "w", encoding="utf-8") as sf:
        json.dump({
            "plan_path": out_path,
            "generated_at": dt.datetime.utcnow().isoformat() + "Z"
        }, sf, ensure_ascii=False, indent=2)

    # Communicate path back to workflow
    os.makedirs("/tmp", exist_ok=True)
    with open("/tmp/PLAN_PATH.txt", "w", encoding="utf-8") as fp:
        fp.write(os.path.relpath(out_path))

    print(f"[plan] Wrote {out_path}")

if __name__ == "__main__":
    main()
