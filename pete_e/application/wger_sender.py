"""Send validated training plans to the Wger API."""

from datetime import date, timedelta
import hashlib
import json
from typing import Any, Dict, Optional

from pete_e.domain.validation import (
    ValidationDecision,
    collect_adherence_snapshot,
    validate_and_adjust_plan,
)
from pete_e.domain.data_access import DataAccessLayer
from pete_e.infrastructure.plan_rw import build_week_payload
from pete_e.infrastructure.wger_exporter_v3 import export_week_to_wger
from pete_e.infrastructure import log_utils


def _summarize_adherence(adherence_snapshot: Optional[Dict[str, Any]]) -> str:
    if not adherence_snapshot:
        return ""

    try:
        ratio = float(adherence_snapshot.get("ratio", 0.0))
        actual_total = float(adherence_snapshot.get("actual_total", 0.0))
        planned_total = float(adherence_snapshot.get("planned_total", 0.0))
    except (TypeError, ValueError):
        return ""

    return (
        f" Adherence ratio {ratio:.2f} "
        f"(actual {actual_total:.1f}kg vs planned {planned_total:.1f}kg)."
    )

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

    decision: ValidationDecision = validate_and_adjust_plan(dal, start_date)
    adherence_snapshot = collect_adherence_snapshot(dal, start_date)
    adherence_summary = _summarize_adherence(adherence_snapshot)
    log_entries = getattr(decision, "log_entries", None) or []
    adjustment_text = ", ".join(log_entries) if log_entries else "none"
    recovery_text = getattr(decision, "explanation", "")
    recovery_clause = ""
    if recovery_text:
        recovery_clause = f" Recovery: {recovery_text}.{adherence_summary}"
    elif adherence_summary:
        recovery_clause = adherence_summary

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
            f"Wger export already exists for plan {plan_id} week {week}; skipping push.{recovery_clause} "
            f"Adjustments: {adjustment_text}.",
            "INFO",
        )
        return {"status": "skipped", "reason": "already-exported"}

    payload = build_week_payload(plan_id, week)
    checksum = _payload_checksum(payload)

    response: Any
    result_status: Dict[str, Any]
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

    log_utils.log_message(
        f"[wger_export] Sent plan {plan_id} week {week} to Wger.{recovery_clause} "
        f"Adjustments: {adjustment_text}. Response: {response}",
        "INFO",
    )

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
