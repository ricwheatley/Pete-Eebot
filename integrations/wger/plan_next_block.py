#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate a 4-week training block plan (weights + Blaze + rest).
- Mon/Tue/Thu/Fri = Weights (1 main + 2 assistance) + Blaze + Core finisher
- Wed = Blaze only
- Sat/Sun = Rest
- Progression based on knowledge/history.json (last 28 days)
- 4-week cycle: Light → Medium → Heavy → Deload
- Assistance lifts progress with their associated main lift
- Blaze = fixed 45-min HIIT class at David Lloyd with set times
- Core finisher = 3 × 1-min rounds, rotated by day + cycle
"""

import argparse
import datetime as dt
import json
import os

KNOWLEDGE_PATH = "knowledge/history.json"
OUT_DIR = "integrations/wger/plans"
STATE_DIR = "integrations/wger/state"

# ---------------- Cycle Intensity Map ---------------- #
WEEK_INTENSITY = {
    1: {"name": "light", "factor": 0.9, "rest_main": 90, "rest_assist": 60, "reps": (8, 10)},
    2: {"name": "medium", "factor": 1.0, "rest_main": 120, "rest_assist": 90, "reps": (6, 8)},
    3: {"name": "heavy", "factor": 1.1, "rest_main": 180, "rest_assist": 150, "reps": (3, 6)},
    4: {"name": "deload", "factor": 0.7, "rest_main": 60, "rest_assist": 45, "reps": (6, 8)},
}

# ---------------- Blaze Schedule ---------------- #
BLAZE_CLASSES = {
    "Mon": {"time": "06:15"},
    "Tue": {"time": "07:00"},
    "Wed": {"time": "07:00"},
    "Thu": {"time": "06:15"},
    "Fri": {"time": "07:15"},
}

# ---------------- Core Rotation ---------------- #
CORE_ROTATION = {
    1: {"Mon": "Plank", "Tue": "Hollow Hold", "Thu": "Side Plank", "Fri": "Bird Dog"},
    2: {"Mon": "Ab Wheel", "Tue": "Hanging Leg Raise", "Thu": "Russian Twist", "Fri": "Deadbug"},
    3: {"Mon": "Cable Woodchop", "Tue": "V-Sit Hold", "Thu": "Toe-to-Bar", "Fri": "Pallof Press"},
    4: {"Mon": "Hollow Rocks", "Tue": "Side Crunch", "Thu": "Plank Shoulder Taps", "Fri": "Dragon Flag"},
}

# ---------------- Main Lifts ---------------- #
MAIN_LIFTS = {
    "Mon": {"id": 615, "name": "Squat", "unilateral": False, "category": "Lower", "default_sets": 4, "default_reps": (5, 8)},
    "Tue": {"id": 73, "name": "Bench Press", "unilateral": False, "category": "Upper", "default_sets": 4, "default_reps": (5, 8)},
    "Thu": {"id": 184, "name": "Deadlift", "unilateral": False, "category": "Lower", "default_sets": 3, "default_reps": (3, 6)},
    "Fri": {"id": 687, "name": "Overhead Press", "unilateral": False, "category": "Upper", "default_sets": 4, "default_reps": (5, 8)},
}

# ---------------- Assistance Pools ---------------- #
ASSISTANCE = {
    "Mon": [
        {"id": 257, "name": "Front Squat", "unilateral": False, "default_sets": 3, "default_reps": (6, 10)},
        {"id": 984, "name": "Lunge", "unilateral": True, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 981, "name": "Step-ups", "unilateral": True, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 371, "name": "Leg Press", "unilateral": False, "default_sets": 3, "default_reps": (10, 15)},
        {"id": 369, "name": "Leg Extension", "unilateral": False, "default_sets": 3, "default_reps": (10, 15)},
        {"id": 622, "name": "Standing Calf Raise", "unilateral": False, "default_sets": 3, "default_reps": (12, 20)},
    ],
    "Tue": [
        {"id": 538, "name": "Incline Bench Press", "unilateral": False, "default_sets": 3, "default_reps": (6, 10)},
        {"id": 194, "name": "Dips", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 238, "name": "Dumbbell Fly", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 76, "name": "Close Grip Bench Press", "unilateral": False, "default_sets": 3, "default_reps": (6, 10)},
        {"id": 660, "name": "Triceps Extension Cable", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 92, "name": "Biceps Curl Dumbbell", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
    ],
    "Thu": [
        {"id": 507, "name": "Romanian Deadlift", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 1392, "name": "Good Morning", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 901, "name": "Barbell Hip Thrust", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 627, "name": "Stiff-Leg Deadlift", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 364, "name": "Leg Curl", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 590, "name": "Seated Calf Raise", "unilateral": False, "default_sets": 3, "default_reps": (12, 20)},
    ],
    "Fri": [
        {"id": 918, "name": "Dumbbell Lateral Raise", "unilateral": False, "default_sets": 3, "default_reps": (10, 15)},
        {"id": 222, "name": "Facepull", "unilateral": False, "default_sets": 3, "default_reps": (12, 15)},
        {"id": 1276, "name": "Incline Dumbbell Press", "unilateral": False, "default_sets": 3, "default_reps": (6, 10)},
        {"id": 571, "name": "Barbell Shrugs", "unilateral": False, "default_sets": 3, "default_reps": (10, 15)},
        {"id": 1185, "name": "Triceps Pushdown", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
        {"id": 91, "name": "Barbell Curl", "unilateral": False, "default_sets": 3, "default_reps": (8, 12)},
    ],
}

# ---------------- Helpers ---------------- #
def load_knowledge():
    if not os.path.exists(KNOWLEDGE_PATH):
        return {}
    with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_progression(history):
    """Return progression factors per main lift based on history."""
    factors = {lift["name"]: 1.0 for lift in MAIN_LIFTS.values()}
    for lift in factors.keys():
        vols = []
        for d, entry in history.get("days", {}).items():
            for ex in entry.get("strength", []):
                if ex.get("exercise_id") == [v["id"] for v in MAIN_LIFTS.values() if v["name"] == lift][0]:
                    vols.append(ex.get("volume_kg", 0))
        if vols:
            if sum(vols[-7:]) > sum(vols[:7]):
                factors[lift] = 1.05
            else:
                factors[lift] = 0.95
    return factors


def merge_reps(default_reps, cycle_reps):
    low = max(default_reps[0], cycle_reps[0])
    high = min(default_reps[1], cycle_reps[1])
    if low > high:
        return default_reps
    return (low, high)


def build_exercise(ex, main_lift, block_factor, week_cfg):
    reps = merge_reps(ex.get("default_reps", (6, 8)), week_cfg["reps"])
    sets = ex.get("default_sets", 3)
    if week_cfg["name"] == "deload":
        sets = max(2, sets - 1)

    base = {
        "id": ex["id"],
        "name": ex["name"],
        "sets": sets,
        "reps": reps,
        "intensity": week_cfg["name"],
        "load_factor": round(block_factor * week_cfg["factor"], 2),
        "rest_seconds": week_cfg["rest_main"] if main_lift else week_cfg["rest_assist"],
    }
    if not ex.get("unilateral", False):
        return [base]
    else:
        left = base.copy(); left["name"] = f"{ex['name']} (Left)"; left["superset"] = True
        right = base.copy(); right["name"] = f"{ex['name']} (Right)"; right["superset"] = True
        return [left, right]


def build_weight_day(main, assistance, factors, week):
    week_cfg = WEEK_INTENSITY[week]
    block_factor = factors.get(main["name"], 1.0)
    lifts = []

    lifts.extend(build_exercise(main, True, block_factor, week_cfg))
    for ex in assistance[:2]:
        lifts.extend(build_exercise(ex, False, block_factor, week_cfg))
    return lifts


def build_blaze(day):
    if day not in BLAZE_CLASSES:
        return None
    return {
        "name": "Blaze",
        "type": "HIIT",
        "duration_min": 45,
        "time": BLAZE_CLASSES[day]["time"],
        "is_class": True,
        "location": "David Lloyd Gym"
    }


def build_core(day, week):
    cycle = (week - 1) % 4 + 1
    ex_name = CORE_ROTATION.get(cycle, {}).get(day)
    if not ex_name:
        return None
    return {
        "type": "core",
        "exercise": ex_name,
        "duration": "3 min (3 × 1 min rounds)"
    }


def build_block(start_date):
    history = load_knowledge()
    progression = compute_progression(history)

    days = []
    for week in range(1, 5):
        for offset in range(7):
            date = start_date + dt.timedelta(days=(week - 1) * 7 + offset)
            day_name = date.strftime("%a")

            entry = {"date": date.isoformat(), "week": week, "day": day_name, "sessions": []}

            if day_name in MAIN_LIFTS:
                main_lift = MAIN_LIFTS[day_name]
                pool = ASSISTANCE[day_name]
                entry["sessions"].append({"type": "weights", "exercises": build_weight_day(main_lift, pool, progression, week)})
                blaze = build_blaze(day_name)
                if blaze:
                    entry["sessions"].append(blaze)
                core = build_core(day_name, week)
                if core:
                    entry["sessions"].append(core)
            elif day_name in BLAZE_CLASSES:
                entry["sessions"].append(build_blaze(day_name))
            else:
                entry["sessions"].append({"type": "rest"})

            days.append(entry)

    return {"start": start_date.isoformat(), "days": days}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", type=str, help="YYYY-MM-DD (Monday)")
    ap.add_argument("--out-dir", type=str, default=OUT_DIR)
    args = ap.parse_args()

    start = dt.date.fromisoformat(args.start_date) if args.start_date else dt.date.today()
    block = build_block(start)

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"plan_{start.isoformat()}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(block, f, indent=2)

    print(f"[plan_next_block] Wrote {out_path}")


if __name__ == "__main__":
    main()