#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Compute a composite "body age" metric from recent Withings and Apple Health histories and
persist the results as JSON files.  This version does not write any CSV logs and stores
per-day outputs under a dedicated directory `docs-body_age`.

Inputs:
  docs/withings/history.json    – rolling history of body composition from Withings
  docs/apple/history.json       – rolling history of activity/heart/sleep from Apple Health

Outputs (created under docs-body_age/):
  <YYYY-MM-DD>.json  – per-day body age record
  daily.json         – latest record, for quick access
  history.json       – list of all records (max 180 days)

The body-age calculation uses 7-day windows for averaging weight, body fat, steps, exercise minutes,
calories (active/rest), heart rate, and sleep.  It then combines cardiorespiratory fitness, body
composition, activity, and recovery into a composite score, from which a "body age" is derived.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime
from typing import Any, Dict, Optional

# Input histories
WITHINGS_HIST = pathlib.Path("docs/withings/history.json")
APPLE_HIST    = pathlib.Path("docs/apple/history.json")

# Output directory (note hyphen per user request)
OUT_DIR = pathlib.Path("docs-body_age")
DAY_DIR = OUT_DIR / "days" # per-day JSON files are written directly here (YYYY-MM-DD.json)
DAILY_PATH = OUT_DIR / "daily.json"
HIST_PATH  = OUT_DIR / "history.json"


def load_hist(p: pathlib.Path):
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def to_float(v: Any) -> Optional[float]:
    try:
        if v in (None, ""):
            return None
        return float(v)
    except Exception:
        return None


def main() -> None:
    wh = load_hist(WITHINGS_HIST)
    ah = load_hist(APPLE_HIST)
    if not wh or not ah:
        print("Missing input data")
        return

    # Map by date for quick lookup
    wm = {r.get("date"): r for r in wh if r.get("date")}
    am = {r.get("date"): r for r in ah if r.get("date")}
    dates = sorted(set(wm) | set(am))
    if not dates:
        return
    dates = dates[-7:]  # last 7 days window

    # Helper: average a function over last 7 days, ignoring None
    def avg_from(fn):
        vals = [to_float(fn(d)) for d in dates]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    weight  = avg_from(lambda d: wm.get(d, {}).get("weight_kg"))
    bodyfat = avg_from(lambda d: wm.get(d, {}).get("body_fat_pct"))
    steps   = avg_from(lambda d: am.get(d, {}).get("steps"))
    exmin   = avg_from(lambda d: am.get(d, {}).get("exercise_minutes"))
    c_act   = avg_from(lambda d: am.get(d, {}).get("calories_active"))
    c_rest  = avg_from(lambda d: am.get(d, {}).get("calories_resting"))
    c_tot   = avg_from(lambda d: am.get(d, {}).get("calories_total"))
    if c_tot is None and (c_act or c_rest):
        c_tot = (c_act or 0) + (c_rest or 0)
    rhr     = avg_from(lambda d: am.get(d, {}).get("hr_resting"))
    hravg   = avg_from(lambda d: am.get(d, {}).get("hr_avg"))
    sleepm  = avg_from(lambda d: (am.get(d, {}).get("sleep_minutes") or {}).get("asleep"))

    # Chronological age assumption; customise as needed
    chrono_age = 44

    # Cardiorespiratory fitness (CRF) via VO2max estimation
    vo2 = None
    if rhr is not None:
        vo2 = 38 - 0.15 * (chrono_age - 40) - 0.15 * ((rhr or 60) - 60) + 0.01 * (exmin or 0)
    if vo2 is None:
        vo2 = 35
    crf = max(0, min(100, ((vo2 - 20) / (60 - 20)) * 100))

    # Body composition score from body fat percentage
    if bodyfat is None:
        body_comp = 50
    elif bodyfat <= 15:
        body_comp = 100
    elif bodyfat >= 30:
        body_comp = 0
    else:
        body_comp = (30 - bodyfat) / (30 - 15) * 100

    # Activity score from steps and exercise minutes
    steps_score = 0 if steps is None else max(0, min(100, (steps / 12000) * 100))
    ex_score    = 0 if exmin is None else max(0, min(100, (exmin / 30) * 100))
    activity    = 0.6 * steps_score + 0.4 * ex_score

    # Recovery score from sleep and resting HR
    if sleepm is None:
        sleep_score = 50
    else:
        diff = abs(sleepm - 450)
        sleep_score = max(0, min(100, 100 - (diff / 150) * 60))

    if rhr is None:
        rhr_score = 50
    elif rhr <= 55:
        rhr_score = 90
    elif rhr <= 60:
        rhr_score = 80
    elif rhr <= 70:
        rhr_score = 60
    elif rhr <= 80:
        rhr_score = 40
    else:
        rhr_score = 20

    recovery = 0.66 * sleep_score + 0.34 * rhr_score

    # Composite score and body age
    composite = 0.40 * crf + 0.25 * body_comp + 0.20 * activity + 0.15 * recovery
    body_age = chrono_age - 0.2 * (composite - 50)
    cap_min = chrono_age - 10
    cap = False
    if body_age < cap_min:
        body_age = cap_min
        cap = True
    age_delta = body_age - chrono_age

    out: Dict[str, Any] = {
        "date": dates[-1],
        "inputs_window_days": 7,
        "subscores": {
            "crf": round(crf, 1),
            "body_comp": round(body_comp, 1),
            "activity": round(activity, 1),
            "recovery": round(recovery, 1),
        },
        "composite": round(composite, 1),
        "body_age_years": round(body_age, 1),
        "age_delta_years": round(age_delta, 1),
        "assumptions": {
            "used_vo2max_direct": False,
            "cap_minus_10_applied": cap,
        },
    }

    # Ensure output directory exists
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Write per-day JSON file
    (DAY_DIR / f"{out['date']}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    # Write daily.json for convenience
    DAILY_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")

    # Append/update history
    history = []  # list of body-age entries
    if HIST_PATH.exists():
        try:
            history = json.loads(HIST_PATH.read_text())
        except Exception:
            history = []
    # Remove any existing entry for this date
    history = [h for h in history if h.get("date") != out["date"]]
    history.append(out)
    # Keep the last 180 days
    history = sorted(history, key=lambda x: x.get("date"))[-180:]
    HIST_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")

    # Print JSON to stdout for CI logs
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
