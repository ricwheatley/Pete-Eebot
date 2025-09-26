# pete_e/application/strength_test_v1.py
#
# Create a 1-week AMRAP test plan and evaluate it to update Training Maxes.
#
# Protocol:
#   - Bench: 1xAMRAP @ 85%
#   - Squat: 1xAMRAP @ 87.5%
#   - OHP:   1xAMRAP @ 85%
#   - Dead:  1xAMRAP @ 90%
#
# e1RM = weight * (1 + reps/30)  (Epley), TM = 90% of e1RM, rounded to 2.5 kg.
#

import math
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from pete_e.domain.schedule_rules import (
    BLAZE_ID, BLAZE_TIMES, weight_slot_for_day,
    SQUAT_ID, BENCH_ID, DEADLIFT_ID, OHP_ID
)
from pete_e.infrastructure.plan_rw import (
    latest_training_max,
    create_test_week_plan,
    insert_workout,
    latest_test_week,
    week_date_range,
    insert_strength_test_result,
    upsert_training_max,
)

from pete_e.infrastructure.plan_rw import build_week_payload
from pete_e.infrastructure.wger_exporter_v3 import export_week_to_wger


TEST_PCTS = {
    BENCH_ID: 85.0,
    SQUAT_ID: 87.5,
    OHP_ID:   85.0,
    DEADLIFT_ID: 90.0,
}

MAIN_LIFT_ORDER = [BENCH_ID, SQUAT_ID, OHP_ID, DEADLIFT_ID]  # Mon, Tue, Thu, Fri


def _round_2p5(x: float) -> float:
    return round(x / 2.5) * 2.5


def _tm_key(ex_id: int) -> Optional[str]:
    return {
        SQUAT_ID: "squat",
        BENCH_ID: "bench",
        DEADLIFT_ID: "deadlift",
        OHP_ID: "ohp",
    }.get(ex_id)


def _target_from_tm(tm_map: Dict[str, Optional[float]], ex_id: int, pct: float) -> Optional[float]:
    key = _tm_key(ex_id)
    tm = tm_map.get(key or "")
    if tm is None:
        return None
    return _round_2p5(tm * pct / 100.0)


def schedule_test_week(start_monday: date) -> Tuple[int, int]:
    """
    Create a 1-week plan flagged as test, with Blaze entries Mon-Fri and
    a single AMRAP main lift on Mon/Tue/Thu/Fri at the test percent.
    Returns (plan_id, week_id).
    """
    plan_id, week_id = create_test_week_plan(start_monday)

    tm_map = latest_training_max()  # may be empty on first ever run

    # Insert Blaze entries for weekdays
    for dow in sorted(BLAZE_TIMES.keys()):
        insert_workout(
            week_id=week_id,
            day_of_week=dow,
            exercise_id=BLAZE_ID,
            sets=1, reps=1,
            rir_cue=None,
            percent_1rm=None,
            target_weight_kg=None,
            scheduled_time=BLAZE_TIMES[dow].strftime("%H:%M:%S"),
            is_cardio=True
        )

    # Insert AMRAP test main lifts
    for dow, ex_id in zip([1, 2, 4, 5], MAIN_LIFT_ORDER):
        pct = TEST_PCTS[ex_id]
        tgt = _target_from_tm(tm_map, ex_id, pct)
        insert_workout(
            week_id=week_id,
            day_of_week=dow,
            exercise_id=ex_id,
            sets=1,
            reps=1,                 # AMRAP will be performed in the gym; we label it in exporter
            rir_cue=None,
            percent_1rm=pct,
            target_weight_kg=tgt,
            scheduled_time=weight_slot_for_day(dow).strftime("%H:%M:%S"),
            is_cardio=False
        )

    # Build a payload with plan_id and week_number
    payload = build_week_payload(plan_id, 1)
    week_start = start_monday
    week_end = week_start + timedelta(days=6)

    # Export and log
    export_week_to_wger(payload, week_start=week_start, week_end=week_end)

    return plan_id, week_id


def _e1rm_epley(weight_kg: float, reps: int) -> float:
    return weight_kg * (1.0 + reps / 30.0)


def _lift_code(ex_id: int) -> Optional[str]:
    return _tm_key(ex_id)


def evaluate_test_week_and_update_tms() -> Optional[Dict[str, str]]:
    """
    Find the latest test week, compute e1RM per main lift from Wger logs over the
    week window, store strength_test_result rows, and upsert training_max per lift.
    """
    from pete_e.infrastructure.plan_rw import conn_cursor
    tw = latest_test_week()
    if not tw:
        return None

    plan_id = tw["plan_id"]
    week_no = tw["week_number"]
    start_date = tw["start_date"]
    week_start, week_end = week_date_range(start_date, week_no)

    # Pull all sets for the four main lifts in that date window
    main_ids = tuple(MAIN_LIFT_ORDER)
    sql = """
    SELECT date, exercise_id, reps, weight_kg
    FROM wger_logs
    WHERE date BETWEEN %s AND %s
      AND exercise_id = ANY(%s)
      AND reps IS NOT NULL
      AND weight_kg IS NOT NULL
      AND reps >= 1 AND reps <= 20
    ORDER BY date, exercise_id, weight_kg DESC, reps DESC;
    """
    best: Dict[int, Tuple[date, int, float, float]] = {}  # ex_id -> (date, reps, weight, e1rm)

    with conn_cursor() as (_, cur):
        cur.execute(sql, (week_start, week_end, list(main_ids)))
        for row in cur.fetchall():
            ex_id = row["exercise_id"]
            reps = int(row["reps"])
            w = float(row["weight_kg"])
            e1 = _e1rm_epley(w, reps)
            if ex_id not in best or e1 > best[ex_id][3]:
                best[ex_id] = (row["date"], reps, w, e1)

    # For each main lift, write result + TM
    updated = 0
    for ex_id in MAIN_LIFT_ORDER:
        if ex_id not in best:
            continue
        test_date, reps, w, e1 = best[ex_id]
        tm = _round_2p5(e1 * 0.90)
        lc = _lift_code(ex_id) or "unknown"
        insert_strength_test_result(
            plan_id=plan_id,
            week_number=week_no,
            lift_code=lc,
            test_date=test_date,
            test_reps=reps,
            test_weight_kg=w,
            e1rm_kg=round(e1, 1),
            tm_kg=tm,
        )
        upsert_training_max(lift_code=lc, tm_kg=tm, measured_at=week_end, source="AMRAP_EPLEY")
        updated += 1

    return {
        "status": "ok",
        "plan_id": str(plan_id),
        "week": str(week_no),
        "start": str(week_start),
        "end": str(week_end),
        "lifts_updated": str(updated),
    }
