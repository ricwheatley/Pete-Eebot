# pete_e/domain/plan_builder.py

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Dict, Any, List, Optional

from pete_e.domain import schedule_rules
from pete_e.domain import validation
from pete_e.domain.data_access import DataAccessLayer
from pete_e.infrastructure import plan_rw


def _pick_random(ids: List[int], k: int) -> List[int]:
    if not ids:
        return []
    if k >= len(ids):
        return random.sample(ids, len(ids))
    return random.sample(ids, k)


def _safe_get_historical_metrics(dal: Any, days: int) -> List[Dict[str, Any]]:
    getter = getattr(dal, "get_historical_metrics", None)
    if not callable(getter):
        return []
    try:
        rows = getter(days)
    except Exception:
        return []
    if not rows:
        return []
    return [row for row in rows if isinstance(row, dict)]

def _conditioning_sets_from_metrics(metrics: List[Dict[str, Any]]) -> int:
    values: List[float] = []
    for row in metrics:
        for key in ("vo2_max", "vo2max"):
            if key not in row:
                continue
            raw = row.get(key)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                values.append(value)
            break
    if not values:
        return 1
    peak = max(values)
    if peak >= 55.0:
        return 3
    if peak >= 50.0:
        return 2
    return 1

def _deload_adjustment(week_key: int) -> int:
    try:
        final_week = max(schedule_rules.WEEK_PCTS)
    except ValueError:
        return 0
    return 1 if week_key == final_week else 0

def _build_stub_plan(dal: Any, start_date: date, weeks: int) -> Dict[str, Any]:
    metrics_history = _safe_get_historical_metrics(dal, max(14, weeks * 7))
    conditioning_sets = _conditioning_sets_from_metrics(metrics_history)
    plan_weeks: List[Dict[str, Any]] = []
    scheme_keys = sorted(schedule_rules.WEEK_PCTS.keys())
    max_scheme_key = scheme_keys[-1] if scheme_keys else 4

    for index in range(weeks):
        week_number = index + 1
        scheme_key = week_number if week_number in schedule_rules.WEEK_PCTS else max_scheme_key
        week_scheme = schedule_rules.WEEK_PCTS.get(scheme_key, schedule_rules.WEEK_PCTS[max_scheme_key])
        reduction = _deload_adjustment(scheme_key)

        week_data: Dict[str, Any] = {
            "week_number": week_number,
            "start_date": start_date + timedelta(days=7 * index),
            "workouts": [],
        }

        for dow in sorted(schedule_rules.MAIN_LIFT_BY_DOW):
            week_data["workouts"].append(
                {
                    "day_of_week": dow,
                    "slot": "conditioning",
                    "exercise_id": schedule_rules.BLAZE_ID,
                    "sets": conditioning_sets,
                    "reps": 1,
                    "rir": None,
                    "percent_1rm": None,
                    "target_weight_kg": None,
                    "is_cardio": True,
                }
            )

            main_id = schedule_rules.MAIN_LIFT_BY_DOW[dow]
            week_data["workouts"].append(
                {
                    "day_of_week": dow,
                    "slot": "main",
                    "exercise_id": main_id,
                    "sets": week_scheme["sets"],
                    "reps": week_scheme["reps"],
                    "rir": week_scheme.get("rir_cue"),
                    "percent_1rm": week_scheme.get("percent_1rm"),
                    "target_weight_kg": None,
                    "is_cardio": False,
                }
            )

            assistance_primary_sets = max(1, schedule_rules.ASSISTANCE_1["sets"] - reduction)
            week_data["workouts"].append(
                {
                    "day_of_week": dow,
                    "slot": "assistance",
                    "exercise_id": None,
                    "sets": assistance_primary_sets,
                    "reps": schedule_rules.ASSISTANCE_1["reps_low"],
                    "rir": schedule_rules.ASSISTANCE_1["rir_cue"],
                    "percent_1rm": None,
                    "target_weight_kg": None,
                    "is_cardio": False,
                }
            )

            assistance_secondary_sets = max(1, schedule_rules.ASSISTANCE_2["sets"] - reduction)
            week_data["workouts"].append(
                {
                    "day_of_week": dow,
                    "slot": "assistance",
                    "exercise_id": None,
                    "sets": assistance_secondary_sets,
                    "reps": schedule_rules.ASSISTANCE_2["reps_low"],
                    "rir": schedule_rules.ASSISTANCE_2["rir_cue"],
                    "percent_1rm": None,
                    "target_weight_kg": None,
                    "is_cardio": False,
                }
            )

            core_sets = max(1, schedule_rules.CORE_SCHEME["sets"] - reduction)
            week_data["workouts"].append(
                {
                    "day_of_week": dow,
                    "slot": "core",
                    "exercise_id": None,
                    "sets": core_sets,
                    "reps": schedule_rules.CORE_SCHEME["reps_low"],
                    "rir": schedule_rules.CORE_SCHEME["rir_cue"],
                    "percent_1rm": None,
                    "target_weight_kg": None,
                    "is_cardio": False,
                }
            )

        plan_weeks.append(week_data)

    return {
        "start_date": start_date,
        "weeks": plan_weeks,
    }

def build_training_block(start_date: date, weeks: int = 4) -> int:
    """
    Build a 4-week block aligned to the blueprint:
      - Mon Bench (after Blaze)
      - Tue Squat (before Blaze)
      - Thu OHP (after Blaze)
      - Fri Deadlift (before Blaze)
    Each session = main lift + 2 assistance + 1 core.
    Blaze (id=1630) is added at fixed times.
    """
    if weeks != 4:
        raise ValueError("Only 4-week blocks are supported")

    # Create block and plan
    plan_id, week_ids = plan_rw.create_block_and_plan(start_date, weeks)

    # Retrieve latest training max values for main lifts
    tm_map = plan_rw.latest_training_max()

    # Iterate weeks
    for w in range(1, weeks + 1):
        week_id = week_ids[w - 1]
        week_start = start_date + timedelta(days=(w - 1) * 7)

        for dow, main_id in schedule_rules.MAIN_LIFT_BY_DOW.items():
            # Blaze first if required
            blaze_time = schedule_rules.BLAZE_TIMES.get(dow)
            if blaze_time:
                plan_rw.insert_workout(
                    week_id=week_id,
                    day_of_week=dow,
                    exercise_id=schedule_rules.BLAZE_ID,
                    sets=1,
                    reps=1,
                    rir_cue=None,
                    percent_1rm=None,
                    target_weight_kg=None,
                    scheduled_time=blaze_time.strftime("%H:%M"),
                    is_cardio=True,
                )

            # Main lift
            scheme = schedule_rules.WEEK_PCTS[w]
            target_weight_kg = None
            lift_code = schedule_rules.LIFT_CODE_BY_ID.get(main_id)
            if lift_code:
                training_max = tm_map.get(lift_code)
                percent_1rm = scheme.get("percent_1rm")
                if training_max is not None and percent_1rm is not None:
                    target_weight_kg = round(
                        training_max * percent_1rm / 100 / 2.5
                    ) * 2.5
            plan_rw.insert_workout(
                week_id=week_id,
                day_of_week=dow,
                exercise_id=main_id,
                sets=scheme["sets"],
                reps=scheme["reps"],
                rir_cue=scheme["rir_cue"],
                percent_1rm=scheme["percent_1rm"],
                target_weight_kg=target_weight_kg,
                scheduled_time=schedule_rules.weight_slot_for_day(dow).strftime("%H:%M"),
                is_cardio=False,
            )

            # Assistance
            pool_ids = plan_rw.assistance_pool_for(main_id)
            chosen = _pick_random(pool_ids, 2)
            if chosen:
                # Assistance 1
                a1_scheme = schedule_rules.ASSISTANCE_1
                plan_rw.insert_workout(
                    week_id=week_id,
                    day_of_week=dow,
                    exercise_id=chosen[0],
                    sets=a1_scheme["sets"] - (1 if w == 4 else 0),
                    reps=a1_scheme["reps_low"],
                    rir_cue=a1_scheme["rir_cue"],
                    percent_1rm=None,
                    target_weight_kg=None,
                    scheduled_time=schedule_rules.weight_slot_for_day(dow).strftime("%H:%M"),
                    is_cardio=False,
                )
                # Assistance 2
                if len(chosen) > 1:
                    a2_scheme = schedule_rules.ASSISTANCE_2
                    plan_rw.insert_workout(
                        week_id=week_id,
                        day_of_week=dow,
                        exercise_id=chosen[1],
                        sets=a2_scheme["sets"] - (1 if w == 4 else 0),
                        reps=a2_scheme["reps_low"],
                        rir_cue=a2_scheme["rir_cue"],
                        percent_1rm=None,
                        target_weight_kg=None,
                        scheduled_time=schedule_rules.weight_slot_for_day(dow).strftime("%H:%M"),
                        is_cardio=False,
                    )

            # Core
            core_ids = plan_rw.core_pool_ids()
            chosen_core = _pick_random(core_ids, 1)
            if chosen_core:
                core_scheme = schedule_rules.CORE_SCHEME
                plan_rw.insert_workout(
                    week_id=week_id,
                    day_of_week=dow,
                    exercise_id=chosen_core[0],
                    sets=core_scheme["sets"] - (1 if w == 4 else 0),
                    reps=core_scheme["reps_low"],
                    rir_cue=core_scheme["rir_cue"],
                    percent_1rm=None,
                    target_weight_kg=None,
                    scheduled_time=schedule_rules.weight_slot_for_day(dow).strftime("%H:%M"),
                    is_cardio=False,
                )

    # Validate the plan structure
    active_plan = plan_rw.get_active_plan()
    if active_plan:
        validation.validate_plan_structure(
            {"weeks": [{"week_number": i + 1, "start_date": start_date + timedelta(days=7 * i),
                        "workouts": plan_rw.plan_week_rows(plan_id, i + 1)} for i in range(weeks)]},
            block_start_date=start_date,
        )

    return plan_id

# Backward compatibility for orchestrator/tests that still expect build_block
def build_block(dal, start_date, weeks: int = 4) -> int:
    """
    Compatibility shim. Persist a plan via the provided DAL when possible.
    """
    weeks = max(1, int(weeks or 1))

    if isinstance(dal, DataAccessLayer):
        return build_training_block(start_date, weeks)

    saver = getattr(dal, "save_training_plan", None)
    if not callable(saver):
        return build_training_block(start_date, weeks)

    plan_payload = _build_stub_plan(dal, start_date, weeks)
    plan_id = saver(plan_payload, start_date)
    try:
        return int(plan_id)
    except (TypeError, ValueError):
        return plan_id


TEST_WEEK_LIFT_ORDER = [
    schedule_rules.BENCH_ID,
    schedule_rules.SQUAT_ID,
    schedule_rules.OHP_ID,
    schedule_rules.DEADLIFT_ID,
]

TEST_WEEK_PCTS = {
    schedule_rules.BENCH_ID: 85.0,
    schedule_rules.SQUAT_ID: 87.5,
    schedule_rules.OHP_ID: 85.0,
    schedule_rules.DEADLIFT_ID: 90.0,
}


def _round_to_2p5(value: float) -> float:
    return round(value / 2.5) * 2.5


def _tm_key_for_lift(exercise_id: int) -> Optional[str]:
    return schedule_rules.LIFT_CODE_BY_ID.get(exercise_id)


def _target_weight_from_tm(tm_map: Dict[str, Optional[float]], exercise_id: int, percent: float) -> Optional[float]:
    code = _tm_key_for_lift(exercise_id)
    if not code:
        return None
    tm = tm_map.get(code)
    if tm is None:
        return None
    return _round_to_2p5(tm * percent / 100.0)


def build_strength_test(dal, start_date: date) -> int:
    """Create a 1-week strength test plan with AMRAP sessions for the main lifts."""

    plan_id, week_id = plan_rw.create_test_week_plan(start_date)

    tm_map = plan_rw.latest_training_max()

    for dow in sorted(schedule_rules.BLAZE_TIMES.keys()):
        plan_rw.insert_workout(
            week_id=week_id,
            day_of_week=dow,
            exercise_id=schedule_rules.BLAZE_ID,
            sets=1,
            reps=1,
            rir_cue=None,
            percent_1rm=None,
            target_weight_kg=None,
            scheduled_time=schedule_rules.BLAZE_TIMES[dow].strftime("%H:%M:%S"),
            is_cardio=True,
        )

    for dow, exercise_id in zip([1, 2, 4, 5], TEST_WEEK_LIFT_ORDER):
        percent = TEST_WEEK_PCTS[exercise_id]
        target_weight = _target_weight_from_tm(tm_map, exercise_id, percent)
        plan_rw.insert_workout(
            week_id=week_id,
            day_of_week=dow,
            exercise_id=exercise_id,
            sets=1,
            reps=1,
            rir_cue=None,
            percent_1rm=percent,
            target_weight_kg=target_weight,
            scheduled_time=schedule_rules.weight_slot_for_day(dow).strftime("%H:%M:%S"),
            is_cardio=False,
        )

    return plan_id


