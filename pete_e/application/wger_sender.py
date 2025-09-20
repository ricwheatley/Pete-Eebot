"""Send validated training plans to the Wger API."""

from datetime import date

from pete_e.domain.validation import validate_and_adjust_plan
from pete_e.domain.data_access import DataAccessLayer
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure import log_utils


def wrangle_week_for_wger(week: dict) -> dict:
    """
    Convert normalized DB week structure into Wger API JSON format.
    """
    payload = {"days": []}
    for workout in week.get("workouts", []):
        day_json = {"day": workout["day_of_week"], "exercises": []}
        for ex in workout["workouts"]:
            day_json["exercises"].append({
                "exercise": ex["exercise_id"],  # Wger expects exercise id
                "sets": ex["sets"],
                "reps": ex["reps"],
                "rir": ex.get("rir"),
            })
        payload["days"].append(day_json)
    return payload


def send_plan_week_to_wger(
    dal: DataAccessLayer,
    plan_id: int,
    week_number: int,
    current_start_date: date,
    client: WgerClient
) -> bool:
    """
    Validate plan → adjust DB → wrangle into Wger JSON → POST to Wger.
    """
    # 1. Validate + adjust
    adjustments = validate_and_adjust_plan(dal, plan_id, week_number, current_start_date)

    # 2. Fetch updated plan week
    plan = dal.get_plan(plan_id)
    week = next((w for w in plan.get("weeks", []) if w["week_number"] == week_number), None)
    if not week:
        log_utils.log_message(f"[send_wger] Plan {plan_id}, week {week_number} not found", "ERROR")
        return False

    # 3. Wrangle into Wger JSON
    payload = wrangle_week_for_wger(week)
    payload["name"] = f"Pete-Eebot Week {week_number}"

    # 4. Send to Wger
    try:
        response = client.post_plan(payload)
        log_utils.log_message(
            f"[send_wger] Sent plan {plan_id} week {week_number} to Wger. "
            f"Adjustments: {adjustments}. Response: {response}",
            "INFO"
        )
        return True
    except Exception as e:
        log_utils.log_message(
            f"[send_wger] Failed to send plan {plan_id} week {week_number} to Wger: {e}",
            "ERROR"
        )
        return False
