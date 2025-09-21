"""Send validated training plans to the Wger API."""

from datetime import date, timedelta
import hashlib
import json
from typing import Any, Dict

from pete_e.domain.validation import ValidationDecision, validate_and_adjust_plan
from pete_e.domain.data_access import DataAccessLayer
from pete_e.infrastructure.plan_rw import build_week_payload
from pete_e.infrastructure.wger_exporter_v3 import export_week_to_wger
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
    decision: ValidationDecision = validate_and_adjust_plan(dal, current_start_date)

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
        adjustment_text = ", ".join(decision.log_entries) if decision.log_entries else "none"
        log_utils.log_message(
            f"[send_wger] Sent plan {plan_id} week {week_number} to Wger. "
            f"Adjustments: {adjustment_text}. Recovery: {decision.explanation}. Response: {response}",
            "INFO"
        )
        return True
    except Exception as e:
        log_utils.log_message(
            f"[send_wger] Failed to send plan {plan_id} week {week_number} to Wger: {e}",
            "ERROR"
        )
        return False

def _payload_checksum(payload: Dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()

def push_week(
    dal: DataAccessLayer,
    plan_id: int,
    week: int = 1,
    *,
    start_date: date,
) -> Dict[str, Any]:
    """Push a single plan week to Wger with idempotency guards."""

    was_exported = False
    checker = getattr(dal, "was_week_exported", None)
    if callable(checker):
        try:
            was_exported = checker(plan_id, week)
        except Exception as exc:
            log_utils.log_message(
                f"Failed to check existing Wger export for plan {plan_id} week {week}: {exc}",
                "ERROR",
            )
            was_exported = False

    if was_exported:
        log_utils.log_message(
            f"Wger export already exists for plan {plan_id} week {week}; skipping push.",
            "INFO",
        )
        return {"status": "skipped", "reason": "already-exported"}

    payload = build_week_payload(plan_id, week)
    checksum = _payload_checksum(payload)

    try:
        response = export_week_to_wger(
            payload,
            week_start=start_date,
            week_end=start_date + timedelta(days=6),
        )
        result_status = {"status": "exported", "response": response, "checksum": checksum}
    except Exception as exc:
        log_utils.log_message(
            f"Failed to export plan {plan_id} week {week} to Wger: {exc}",
            "ERROR",
        )
        raise

    recorder = getattr(dal, "record_wger_export", None)
    if callable(recorder):
        routine_id = response.get("routine_id") if isinstance(response, dict) else None
        try:
            recorder(plan_id, week, payload, response if isinstance(response, dict) else None, routine_id)
        except Exception as exc:
            log_utils.log_message(
                f"Failed to record Wger export log for plan {plan_id} week {week}: {exc}",
                "WARN",
            )

    return result_status
