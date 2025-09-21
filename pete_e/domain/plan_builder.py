# (Functional) Training plan generator (simple 4-week block logic) – uses DataAccess interface to fetch metrics & save plan.

"""
Training plan builder for Pete-Eebot.

This version builds a structured multi-week plan based on recent metrics,
and persists it into the normalized PostgreSQL schema via the DAL.
"""

from datetime import date, timedelta
from typing import Dict, Any

from pete_e.domain.data_access import DataAccessLayer
from pete_e.config import settings


def build_block(dal: DataAccessLayer, start_date: date, weeks: int = 4) -> int:
    """
    Construct a training block and persist it to the database.

    Uses historical metrics for adaptation (HR, sleep) to determine intensity.

    Args:
        dal: DataAccessLayer instance for DB operations.
        start_date: The start date of the training plan.
        weeks: Number of weeks to include in the plan.

    Returns:
        plan_id (int): The primary key of the saved training plan in Postgres.
    """

    existing_lookup = getattr(dal, "find_plan_by_start_date", None)
    if callable(existing_lookup):
        try:
            existing = existing_lookup(start_date)
        except Exception:
            existing = None
        if isinstance(existing, dict) and existing.get("id") is not None:
            return int(existing["id"])

    # Fetch context
    recent_metrics = dal.get_historical_metrics(7)  # last 7 days
    if not recent_metrics:
        raise RuntimeError("No historical metrics available to seed plan building")

    # Simplified adaptation logic
    avg_rhr = sum([m.get("hr_resting") or 0 for m in recent_metrics if m.get("hr_resting")]) / max(
        1, len([m for m in recent_metrics if m.get("hr_resting")])
    )
    avg_sleep = sum([m.get("sleep_asleep_minutes") or 0 for m in recent_metrics if m.get("sleep_asleep_minutes")]) / max(
        1, len([m for m in recent_metrics if m.get("sleep_asleep_minutes")])
    )

    recovery_good = (
        avg_sleep >= settings.RECOVERY_SLEEP_THRESHOLD_MINUTES
        and avg_rhr <= settings.RECOVERY_RHR_THRESHOLD
    )

    heavy_days = ["Mon", "Thu"] if recovery_good else ["Tue", "Fri"]

    # ---------------------------------------------------------------------
    # Build plan structure in memory
    # ---------------------------------------------------------------------
    weeks_out = []
    for week_index in range(1, weeks + 1):
        week_days = []
        for day_offset in range(7):
            d = start_date + timedelta(days=(week_index - 1) * 7 + day_offset)
            dow = d.isoweekday()  # 1=Mon … 7=Sun

            day_entry: Dict[str, Any] = {
                "day_of_week": dow,
                "workouts": []
            }

            # crude example split
            if d.strftime("%a") in heavy_days:
                # chest-focused day, heavy load
                day_entry["workouts"].append({
                    "exercise_id": 192,  # e.g. Bench Press in Wger
                    "sets": 5,
                    "reps": 5,
                    "rir": 2
                })
            elif d.strftime("%a") == "Wed":
                # HIIT / cardio session
                day_entry["workouts"].append({
                    "exercise_id": 345,  # e.g. Burpees or another cardio-type
                    "sets": 1,
                    "reps": 1,
                    "rir": None
                })
            else:
                # rest day (no workouts)
                pass

            if day_entry["workouts"]:
                week_days.append(day_entry)

        weeks_out.append({"week_number": week_index, "workouts": week_days})

    plan = {"weeks": weeks_out}

    # ---------------------------------------------------------------------
    # Save to DB
    # ---------------------------------------------------------------------
    plan_id = dal.save_training_plan(plan, start_date)
    if not plan_id:
        raise RuntimeError("Failed to persist training plan to database")

    return plan_id
