"""
Validation logic for Pete-Eebot.
Runs recovery-based checks using DB metrics and adjusts training plans in Postgres.
"""

from datetime import date, timedelta
from typing import List

from pete_e.data_access.dal import DataAccessLayer
from pete_e.config import settings
from pete_e.infra import log_utils


def validate_and_adjust_plan(
    dal: DataAccessLayer,
    plan_id: int,
    week_number: int,
    current_start_date: date,
) -> List[str]:
    """
    Run validation checks against DB metrics and adjust the training plan in Postgres.

    Args:
        dal: Postgres DAL
        plan_id: Training plan ID to validate
        week_number: The plan week to validate
        current_start_date: Start date of the plan (for logging context)

    Returns:
        List of adjustment notes applied.
    """

    adjustments: List[str] = []
    global_backoff = False

    # -----------------------------------------------------------------
    # 1. Fetch recent metrics
    # -----------------------------------------------------------------
    end_date = date.today()
    start_date = end_date - timedelta(days=7)

    metrics = dal.get_historical_data(start_date, end_date)

    avg_rhr = sum([m.get("hr_resting") or 0 for m in metrics if m.get("hr_resting")]) / max(
        1, len([m for m in metrics if m.get("hr_resting")])
    )
    avg_sleep = sum([m.get("sleep_asleep_minutes") or 0 for m in metrics if m.get("sleep_asleep_minutes")]) / max(
        1, len([m for m in metrics if m.get("sleep_asleep_minutes")])
    )
    avg_body_age_delta = sum([m.get("body_age_delta_years") or 0 for m in metrics if m.get("body_age_delta_years")]) / max(
        1, len([m for m in metrics if m.get("body_age_delta_years")])
    )

    # -----------------------------------------------------------------
    # 2. Recovery checks
    # -----------------------------------------------------------------
    if avg_rhr > settings.RHR_BASELINE * (1 + settings.RHR_ALLOWED_INCREASE):
        adjustments.append(f"Global back-off: ↑ RHR {avg_rhr:.1f} > baseline")
        global_backoff = True

    if avg_sleep < settings.SLEEP_BASELINE * (1 - settings.SLEEP_ALLOWED_DECREASE):
        adjustments.append(f"Global back-off: ↓ sleep {avg_sleep:.0f}m < baseline")
        global_backoff = True

    if avg_body_age_delta > settings.BODY_AGE_ALLOWED_INCREASE:
        adjustments.append(f"Global back-off: body age worsened {avg_body_age_delta:.1f}y")
        global_backoff = True

    # -----------------------------------------------------------------
    # 3. Apply updates to DB
    # -----------------------------------------------------------------
    if global_backoff:
        try:
            with dal._pool.connection() as conn, conn.cursor() as cur:  # direct pool use
                cur.execute(
                    """
                    UPDATE training_plan_workouts
                    SET sets = ROUND(sets * %s),
                        rir = COALESCE(rir, 0) + 1
                    WHERE week_id IN (
                        SELECT id FROM training_plan_weeks
                        WHERE plan_id = %s AND week_number = %s
                    );
                    """,
                    (settings.GLOBAL_BACKOFF_FACTOR, plan_id, week_number),
                )
            log_utils.log_message(f"[validation] Applied global back-off to plan {plan_id}, week {week_number}", "INFO")
        except Exception as e:
            log_utils.log_message(f"[validation] Failed to update plan {plan_id}: {e}", "ERROR")

    # -----------------------------------------------------------------
    # 4. Log adjustments
    # -----------------------------------------------------------------
    if adjustments:
        dal.save_validation_log(
            f"validation_week{week_number}_{current_start_date.isoformat()}",
            adjustments,
        )

    return adjustments
