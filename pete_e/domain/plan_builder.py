# pete_e/domain/plan_builder.py

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Dict, Any, List

from pete_e.domain import schedule_rules
from pete_e.domain import validation
from pete_e.infrastructure import plan_rw


def _pick_random(ids: List[int], k: int) -> List[int]:
    if not ids:
        return []
    if k >= len(ids):
        return random.sample(ids, len(ids))
    return random.sample(ids, k)


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
            plan_rw.insert_workout(
                week_id=week_id,
                day_of_week=dow,
                exercise_id=main_id,
                sets=scheme["sets"],
                reps=scheme["reps"],
                rir_cue=scheme["rir_cue"],
                percent_1rm=scheme["percent_1rm"],
                target_weight_kg=None,  # filled later by progression
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
    Compatibility shim. Ignore `dal` and call build_training_block.
    """
    return build_training_block(start_date, weeks)


