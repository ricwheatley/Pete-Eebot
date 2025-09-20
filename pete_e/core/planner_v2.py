# pete_e/core/planner_v2.py

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta, time
from typing import Dict, List, Optional, Tuple

from pete_e.core.schedule_rules import (
    BLAZE_ID, BLAZE_TIMES, MAIN_LIFT_BY_DOW, WEEK_PCTS,
    weight_slot_for_day, SQUAT_ID, BENCH_ID, DEADLIFT_ID, OHP_ID,
    ASSISTANCE_1, ASSISTANCE_2, CORE_SCHEME
)
from pete_e.infrastructure.plan_rw import (
    latest_training_max,
    assistance_pool_for,
    core_pool_ids,
    create_block_and_plan,
    insert_workout
)

@dataclass
class Prescription:
    sets: int
    reps: int
    percent_1rm: float
    rir_cue: float

def round_to_2p5(x: float) -> float:
    return round(x / 2.5) * 2.5

def tm_key_for_exercise(ex_id: int) -> Optional[str]:
    if ex_id == SQUAT_ID:
        return "squat"
    if ex_id == BENCH_ID:
        return "bench"
    if ex_id == DEADLIFT_ID:
        return "deadlift"
    if ex_id == OHP_ID:
        return "ohp"
    return None

def target_weight(tm_map: Dict[str, Optional[float]], ex_id: int, pct: float) -> Optional[float]:
    key = tm_key_for_exercise(ex_id)
    if key is None:
        return None
    tm = tm_map.get(key)
    if tm is None:
        return None
    return round_to_2p5(tm * pct / 100.0)

def monday_of_week(start: date) -> date:
    # Ensure start is a Monday - if it is Sunday, add one day; if any other weekday, compute delta
    return start if start.weekday() == 0 else start + timedelta(days=(7 - start.weekday()))

def build_block(start_date: date) -> Tuple[int, List[int]]:
    """
    Build a 4-week block starting from the Monday on or after start_date.
    Returns (plan_id, [week_ids]).
    """
    block_monday = monday_of_week(start_date)
    plan_id, week_ids = create_block_and_plan(start_date=block_monday, weeks=4)

    # Pull latest training maxes
    tm_map = latest_training_max()  # keys: squat, bench, deadlift, ohp

    # Preload pools
    core_ids = core_pool_ids()

    # Rotation guards - avoid repeating same assistance within the block for the same main lift
    used_assistance: Dict[int, set] = {SQUAT_ID: set(), BENCH_ID: set(), DEADLIFT_ID: set(), OHP_ID: set()}
    used_core: set = set()

    for week_idx, week_id in enumerate(week_ids, start=1):
        pres = WEEK_PCTS[week_idx]
        pres_obj = Prescription(
            sets=pres["sets"], reps=pres["reps"],
            percent_1rm=pres["percent_1rm"], rir_cue=pres["rir_cue"]
        )

        # Build Mon..Sun relative to block_monday
        for dow in range(1, 8):  # 1=Mon ... 7=Sun
            day_date = block_monday + timedelta(days=(week_idx - 1)*7 + (dow - 1))

            # Insert Blaze on weekdays
            if dow in BLAZE_TIMES:
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

            # Lifting days Mon, Tue, Thu, Fri
            main_ex = MAIN_LIFT_BY_DOW.get(dow)
            if not main_ex:
                continue

            # Main lift prescription
            tgt_kg = target_weight(tm_map, main_ex, pres_obj.percent_1rm)
            insert_workout(
                week_id=week_id,
                day_of_week=dow,
                exercise_id=main_ex,
                sets=pres_obj.sets,
                reps=pres_obj.reps,
                rir_cue=pres_obj.rir_cue,
                percent_1rm=pres_obj.percent_1rm,
                target_weight_kg=tgt_kg,
                scheduled_time=weight_slot_for_day(dow).strftime("%H:%M:%S"),
                is_cardio=False
            )

            # Assistance selection for this main lift
            pool = assistance_pool_for(main_ex)
            random.seed(f"{plan_id}:{week_id}:{dow}")
            # pick 2 unique assistance not used before this block for this main lift
            choices = [e for e in pool if e not in used_assistance[main_ex]]
            if len(choices) < 2:
                # reset if pool exhausted
                used_assistance[main_ex] = set()
                choices = [e for e in pool]
            random.shuffle(choices)
            a1, a2 = choices[0], choices[1]
            used_assistance[main_ex].update({a1, a2})

            # Assistance #1 3x10-12
            insert_workout(
                week_id=week_id,
                day_of_week=dow,
                exercise_id=a1,
                sets=ASSISTANCE_1["sets"],
                reps=ASSISTANCE_1["reps_high"] if week_idx == 1 else ASSISTANCE_1["reps_low"],
                rir_cue=ASSISTANCE_1["rir_cue"],
                percent_1rm=None,
                target_weight_kg=None,
                scheduled_time=weight_slot_for_day(dow).strftime("%H:%M:%S"),
                is_cardio=False
            )

            # Assistance #2 3x8-10
            insert_workout(
                week_id=week_id,
                day_of_week=dow,
                exercise_id=a2,
                sets=ASSISTANCE_2["sets"],
                reps=ASSISTANCE_2["reps_high"] if week_idx == 1 else ASSISTANCE_2["reps_low"],
                rir_cue=ASSISTANCE_2["rir_cue"],
                percent_1rm=None,
                target_weight_kg=None,
                scheduled_time=weight_slot_for_day(dow).strftime("%H:%M:%S"),
                is_cardio=False
            )

            # Core pick
            if core_ids:
                core_choices = [e for e in core_ids if e not in used_core]
                if len(core_choices) == 0:
                    used_core = set()
                    core_choices = core_ids[:]
                random.shuffle(core_choices)
                core_ex = core_choices[0]
                used_core.add(core_ex)
                insert_workout(
                    week_id=week_id,
                    day_of_week=dow,
                    exercise_id=core_ex,
                    sets=CORE_SCHEME["sets"],
                    reps=CORE_SCHEME["reps_low"],
                    rir_cue=CORE_SCHEME["rir_cue"],
                    percent_1rm=None,
                    target_weight_kg=None,
                    scheduled_time=weight_slot_for_day(dow).strftime("%H:%M:%S"),
                    is_cardio=False
                )

    return plan_id, week_ids
