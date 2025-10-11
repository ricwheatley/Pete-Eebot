from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Dict, List, Optional

from pete_e.domain.data_access import DataAccessLayer
from pete_e.domain.validation import (
    PlanContext,
    ValidationDecision,
    collect_adherence_snapshot,
    resolve_plan_context,
    validate_and_adjust_plan as domain_validate_and_adjust,
)
from pete_e.infrastructure import log_utils


from .plan_context_service import ApplicationPlanService


class ValidationService:
    """Application service responsible for coordinating validation data."""

    def __init__(
        self,
        dal: DataAccessLayer,
        plan_service: Optional[ApplicationPlanService] = None,
    ) -> None:
        self._dal = dal
        self._plan_service = plan_service or ApplicationPlanService(dal)

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

    def _build_adherence_snapshot(
        self,
        week_start: date,
        plan_context: Optional[PlanContext],
        planned_rows: List[Dict[str, object]],
        actual_rows: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if not plan_context:
            return None
        plan_id = plan_context.plan_id
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

    def validate_and_adjust_plan(
        self,
        week_start: date,
        *,
        apply_adjustment: bool = True,
    ) -> ValidationDecision:
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

        decision = domain_validate_and_adjust(
            historical_rows,
            week_start,
            plan_context=plan_context,
            adherence_snapshot=adherence_snapshot,
        )

        applied = decision.applied
        log_entries = list(decision.log_entries)

        if apply_adjustment and decision.should_apply:
            try:
                self._dal.apply_plan_backoff(
                    week_start,
                    set_multiplier=decision.recommendation.set_multiplier,
                    rir_increment=decision.recommendation.rir_increment,
                )
            except Exception as exc:  # pragma: no cover - DB failures are environment-specific
                log_utils.log_message(f"Failed to apply back-off: {exc}", "ERROR")
                log_entries.append(f"apply_failed: {exc}")
                applied = False
            else:
                log_utils.log_message(
                    "Applied plan adjustment to upcoming week.",
                    "INFO",
                )
                applied = True

        return replace(decision, log_entries=log_entries, applied=applied)
