from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from pete_e.domain.data_access import DataAccessLayer
from pete_e.domain.validation import (
    MAX_BASELINE_WINDOW_DAYS,
    ValidationDecision,
    collect_adherence_snapshot,
    validate_and_adjust_plan as domain_validate_and_adjust,
)
from pete_e.infrastructure import log_utils
from pete_e.utils import converters


class ValidationService:
    """Application service responsible for coordinating validation data."""

    def __init__(self, dal: DataAccessLayer) -> None:
        self._dal = dal

    def _resolve_plan_context(self, week_start: date) -> Optional[Tuple[int, date]]:
        plan: Optional[Dict[str, object]] = None
        try:
            plan = self._dal.get_active_plan()
        except Exception:
            plan = None
        if plan:
            plan_id = plan.get("id")
            start = converters.to_date(plan.get("start_date"))
            if plan_id is not None and start is not None:
                return int(plan_id), start

        try:
            plan = self._dal.find_plan_by_start_date(week_start)
        except Exception:
            plan = None
        if plan:
            plan_id = plan.get("id")
            start = converters.to_date(plan.get("start_date")) or week_start
            if plan_id is not None and start is not None:
                return int(plan_id), start
        return None

    def _load_historical_rows(self, week_start: date) -> List[Dict[str, object]]:
        obs_end = week_start - timedelta(days=1)
        base_start = obs_end - timedelta(days=MAX_BASELINE_WINDOW_DAYS - 1)
        try:
            return self._dal.get_historical_data(start_date=base_start, end_date=obs_end)
        except Exception:
            return []

    def _build_adherence_snapshot(self, week_start: date) -> Optional[Dict[str, object]]:
        context = self._resolve_plan_context(week_start)
        if not context:
            return None
        plan_id, plan_start = context

        days_since_start = (week_start - plan_start).days
        if days_since_start < 0:
            return None
        week_number = (days_since_start // 7) + 1
        prev_week_number = week_number - 1
        if prev_week_number <= 0:
            return None

        try:
            planned_rows = self._dal.get_plan_muscle_volume(plan_id, prev_week_number) or []
        except Exception:
            return None
        if not planned_rows:
            return None

        prev_week_start = week_start - timedelta(days=7)
        prev_week_end = week_start - timedelta(days=1)
        try:
            actual_rows = self._dal.get_actual_muscle_volume(prev_week_start, prev_week_end) or []
        except Exception:
            actual_rows = []

        return collect_adherence_snapshot(
            plan_id=plan_id,
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
        return self._build_adherence_snapshot(week_start)

    def validate_and_adjust_plan(
        self,
        week_start: date,
        *,
        apply_adjustment: bool = True,
    ) -> ValidationDecision:
        historical_rows = self._load_historical_rows(week_start)
        adherence_snapshot = self._build_adherence_snapshot(week_start)

        decision = domain_validate_and_adjust(
            historical_rows,
            week_start,
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
