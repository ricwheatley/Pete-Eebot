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


def load_knowledge():
    if not os.path.exists(KNOWLEDGE_PATH):
        return {}
    with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_block(start_date):
    """Build a 4-week cycle grouped by weeks."""
    history = load_knowledge()

    weeks = []
    for wekindex in range(1, 5):  # week 1 to 4
        days = []
        for day_offset in range(0 , 7):
            d = start_date + dt.timedelta(days=((wekindex-1) * 7 + day_offset)
            day_name = d.strftime("%a")
            entry = {"date": d.isoformat(), "week": wekindex, "day": day_name, "sessions": []}
            if day_name in ["Mon", "Tue", "Thu", "Fri"]:
                entry["sessions"].append({"type": "weights", "exercises": []})
            elif day_name in ["Wed"]:
                entry["sessions"].append({"type": "hiit", "name": "Blaze", "duration_min": 45, "time": "07:00", "is_class": True, "location": "David Lloyd Gym"})
            elif day_name in ["Sat", "Sun"]:
                entry["sessions"].append({"type": "rest"})

            days.append(entry)
        weeks.append({"week_index": wekindex, "days": days})

    return {"start": start_date.isoformat(), "weeks": weeks}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    args = parser.parse_args()
    start_date = dt.date.fromisoformat(args.start_date)
    block = build_block(start_date)
    os.makedir(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"plan_{start_date.isoformat()}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(block, f, indent=2)
    print(f"[build_block] Wrote {out_path}")
