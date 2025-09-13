"""
Validation logic for Pete-E.
Handles recovery-based checks: RHR, sleep, body age.
Applies global back-off if needed and writes logs.
"""

from typing import Tuple

from pete_e.data_access.dal import DataAccessLayer
from pete_e.config import settings


def check_recovery(
    dal: DataAccessLayer,
    week: dict,
    current_start_date: str,
    rhr_baseline: float,
    rhr_last_week: float,
    sleep_baseline: float,
    sleep_last_week: float,
    body_age_delta: float,
) -> Tuple[dict, list[str]]:
    """
    Apply recovery checks and adjust weights globally if needed.

    Args:
        week: Training week dictionary.
        current_start_date: Start date of the current cycle.
        rhr_baseline: 28-day baseline RHR.
        rhr_last_week: Average RHR over last 7 days.
        sleep_baseline: 28-day baseline sleep minutes.
        sleep_last_week: Average sleep minutes over last 7 days.
        body_age_delta: Change in body age vs. chronological.

    Returns:
        (adjusted_week, adjustment_logs)
    """
    adjustments = []
    global_backoff = False

    if (
        rhr_baseline
        and rhr_last_week
        and rhr_last_week > rhr_baseline * (1 + settings.RHR_ALLOWED_INCREASE)
    ):
        adjustments.append(
            f"Global back-off: ↑ RHR >{int(settings.RHR_ALLOWED_INCREASE*100)}% baseline"
        )
        global_backoff = True

    if (
        sleep_baseline
        and sleep_last_week
        and sleep_last_week < sleep_baseline * settings.SLEEP_ALLOWED_DECREASE
    ):
        adjustments.append(
            f"Global back-off: ↓ sleep <{int(settings.SLEEP_ALLOWED_DECREASE*100)}% baseline"
        )
        global_backoff = True

    if body_age_delta > settings.BODY_AGE_ALLOWED_INCREASE:
        adjustments.append(
            f"Global back-off: body age worsened >{settings.BODY_AGE_ALLOWED_INCREASE} years"
        )
        global_backoff = True

    if global_backoff:
        for day in week["days"]:
            for session in day.get("sessions", []):
                if session.get("type") == "weights":
                    for ex in session["exercises"]:
                        ex["weight_target"] *= settings.GLOBAL_BACKOFF_FACTOR

    # Persist validation outcome via the DAL for centralized logging
    dal.save_validation_log(
        f"validation_week{week['week_index']}_{current_start_date}", adjustments
    )

    return week, adjustments
