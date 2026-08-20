from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, timedelta
import hashlib
import json
from typing import Any, Dict, List, Optional

from pete_e.domain.data_access import DataAccessLayer
from pete_e.domain.validation import (
    PlanContext,
    READINESS_ADJUSTMENT_POLICY_VERSION,
    ValidationDecision,
    assess_plan_adjustment as domain_assess_plan_adjustment,
    collect_adherence_snapshot,
    resolve_plan_context,
)
from pete_e.infrastructure import log_utils


from .plan_context_service import ApplicationPlanService


class ValidationService:
    """Application service responsible for coordinating validation data."""

    def __init__(
        self,
        dal: DataAccessLayer,
        plan_service: Optional[ApplicationPlanService] = None,
        *,
        policy_version: str = READINESS_ADJUSTMENT_POLICY_VERSION,
    ) -> None:
        self._dal = dal
        self._plan_service = plan_service or ApplicationPlanService(dal)
        self._policy_version = policy_version
        """Initialize this object."""

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _identity_hash(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical_json(value).encode("utf-8")).hexdigest()

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        return json.loads(cls._canonical_json(value))

    def _baseline_prescription(
        self,
        plan_id: Optional[int],
        week_number: Optional[int],
    ) -> List[Dict[str, Any]]:
        if plan_id is None or week_number is None:
            return []
        try:
            rows = self._dal.get_plan_week_rows(plan_id, week_number)
        except Exception:
            return []

        baseline = [
            {
                "workout_id": row.get("id"),
                "day_of_week": row.get("day_of_week"),
                "exercise_id": row.get("exercise_id"),
                "baseline_sets": row.get("baseline_sets", row.get("sets")),
                "baseline_rir": row.get("baseline_rir", row.get("rir")),
            }
            for row in rows
            if isinstance(row, dict) and not bool(row.get("is_cardio"))
        ]
        return sorted(
            baseline,
            key=lambda item: (
                str(item.get("workout_id")),
                str(item.get("day_of_week")),
                str(item.get("exercise_id")),
            ),
        )

    @staticmethod
    def _target_week_number(
        plan_context: Optional[PlanContext],
        week_start: date,
    ) -> Optional[int]:
        if plan_context is None:
            return None
        days_since_start = (week_start - plan_context.start_date).days
        if days_since_start < 0:
            return None
        return (days_since_start // 7) + 1

    def _load_validation_payload(self, week_start: date) -> Dict[str, object]:
        base: Dict[str, object] = {
            "plan": None,
            "historical_rows": [],
            "planned_rows": [],
            "actual_rows": [],
        }

        try:
            payload = self._dal.get_data_for_validation(week_start)
        except Exception:
            return base

        if not isinstance(payload, dict):
            return base

        merged = {**base, **payload}
        for key in ("historical_rows", "planned_rows", "actual_rows"):
            value = merged.get(key)
            if isinstance(value, list):
                continue
            if value is None:
                merged[key] = []
            else:
                merged[key] = list(value)
        return merged
        """Perform load validation payload."""

    def _build_adherence_snapshot(
        self,
        week_start: date,
        plan_context: Optional[PlanContext],
        planned_rows: List[Dict[str, object]],
        actual_rows: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if not plan_context:
            return None
        plan_start = plan_context.start_date

        days_since_start = (week_start - plan_start).days
        if days_since_start < 0:
            return None
        week_number = (days_since_start // 7) + 1
        prev_week_number = week_number - 1
        if prev_week_number <= 0:
            return None

        if not planned_rows:
            return None

        prev_week_start = week_start - timedelta(days=7)
        prev_week_end = week_start - timedelta(days=1)

        return collect_adherence_snapshot(
            plan_context=plan_context,
            week_number=prev_week_number,
            week_start=prev_week_start,
            week_end=prev_week_end,
            planned_rows=planned_rows,
            actual_rows=actual_rows,
        )
        """Perform build adherence snapshot."""

    def get_adherence_snapshot(
        self, week_start: date
    ) -> Optional[Dict[str, object]]:
        """Expose adherence snapshot for consumers that need summary data."""
        payload = self._load_validation_payload(week_start)
        plan_context = resolve_plan_context(payload.get("plan"), default_start=week_start)
        if plan_context is None:
            plan_context = self._plan_service.get_plan_context(week_start)
        planned_rows = payload.get("planned_rows", [])
        actual_rows = payload.get("actual_rows", [])
        return self._build_adherence_snapshot(week_start, plan_context, planned_rows, actual_rows)

    def assess_plan(self, week_start: date) -> ValidationDecision:
        """Assess readiness without mutating the persisted plan."""

        payload = self._load_validation_payload(week_start)
        plan_context = resolve_plan_context(payload.get("plan"), default_start=week_start)
        if plan_context is None:
            plan_context = self._plan_service.get_plan_context(week_start)
        historical_rows = payload.get("historical_rows", [])
        planned_rows = payload.get("planned_rows", [])
        actual_rows = payload.get("actual_rows", [])
        adherence_snapshot = self._build_adherence_snapshot(
            week_start,
            plan_context,
            planned_rows,
            actual_rows,
        )

        decision = domain_assess_plan_adjustment(
            historical_rows,
            week_start,
            plan_context=plan_context,
            adherence_snapshot=adherence_snapshot,
        )
        plan_id = plan_context.plan_id if plan_context is not None else None
        week_number = self._target_week_number(plan_context, week_start)
        baseline = self._baseline_prescription(plan_id, week_number)
        observation_dates = [
            str(row.get("date"))
            for row in historical_rows
            if isinstance(row, dict) and row.get("date") is not None
        ]
        source_summary = {
            "historical_row_count": len(historical_rows),
            "observation_start": min(observation_dates) if observation_dates else None,
            "observation_end": max(observation_dates) if observation_dates else None,
            "adherence": adherence_snapshot,
        }
        source_data_hash = self._identity_hash(
            {
                "week_start": week_start,
                "historical_rows": historical_rows,
                "adherence_snapshot": adherence_snapshot,
            }
        )
        baseline_hash = self._identity_hash(baseline)
        return replace(
            decision,
            policy_version=self._policy_version,
            source_data_hash=source_data_hash,
            baseline_prescription_hash=baseline_hash,
            source_summary=self._json_safe(source_summary),
            plan_id=plan_id,
            week_number=week_number,
            week_start=week_start,
            applied=False,
            adjustment_id=None,
        )

    def apply_adjustment(
        self,
        decision: ValidationDecision,
        *,
        plan_id: Optional[int] = None,
        week_number: Optional[int] = None,
        week_start: Optional[date] = None,
    ) -> ValidationDecision:
        """Converge one plan week to a durable readiness decision."""

        target_plan_id = plan_id if plan_id is not None else decision.plan_id
        target_week_number = week_number if week_number is not None else decision.week_number
        target_week_start = week_start or decision.week_start
        if target_plan_id is not None and target_week_number is not None:
            target_baseline = self._baseline_prescription(target_plan_id, target_week_number)
            target_baseline_hash = self._identity_hash(target_baseline)
            if (
                target_baseline_hash != decision.baseline_prescription_hash
                or target_plan_id != decision.plan_id
                or target_week_number != decision.week_number
            ):
                decision = replace(
                    decision,
                    baseline_prescription_hash=target_baseline_hash,
                    applied=False,
                    adjustment_id=None,
                )
        if (
            target_plan_id is None
            or target_week_number is None
            or target_week_start is None
            or not decision.source_data_hash
            or not decision.baseline_prescription_hash
        ):
            log_entries = [*decision.log_entries, "apply_skipped: missing durable adjustment identity"]
            return replace(decision, log_entries=log_entries, applied=False)

        audit_payload = self._json_safe(asdict(replace(decision, applied=False, adjustment_id=None)))
        try:
            result = self._dal.apply_plan_adjustment(
                plan_id=target_plan_id,
                week_number=target_week_number,
                week_start_date=target_week_start,
                policy_version=decision.policy_version,
                source_data_hash=decision.source_data_hash,
                baseline_prescription_hash=decision.baseline_prescription_hash,
                set_multiplier=decision.recommendation.set_multiplier,
                rir_increment=decision.recommendation.rir_increment,
                source_summary=decision.source_summary,
                decision_payload=audit_payload,
            )
        except Exception as exc:  # pragma: no cover - DB failures are environment-specific
            log_utils.log_message(f"Failed to apply readiness adjustment: {exc}", "ERROR")
            log_entries = [*decision.log_entries, f"apply_failed: {exc}"]
            return replace(decision, log_entries=log_entries, applied=False)

        adjustment_id = result.get("adjustment_id") if isinstance(result, dict) else None
        log_utils.log_message(
            f"Applied readiness decision to plan {target_plan_id}, week {target_week_number}.",
            "INFO",
        )
        return replace(
            decision,
            applied=True,
            plan_id=target_plan_id,
            week_number=target_week_number,
            week_start=target_week_start,
            adjustment_id=adjustment_id,
        )

    def validate_and_adjust_plan(
        self,
        week_start: date,
        *,
        apply_adjustment: bool = True,
    ) -> ValidationDecision:
        """Compatibility composition of pure assessment and explicit application."""

        decision = self.assess_plan(week_start)
        if not apply_adjustment:
            return decision
        return self.apply_adjustment(decision)
        """Perform validate and adjust plan."""
