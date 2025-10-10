"""Domain service encapsulating cycle rollover logic."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict


class CycleService:
    """Provides domain logic related to training cycle transitions."""

    def __init__(self, *, rollover_weeks: int = 4, trigger_weekday: int = 6) -> None:
        """Create a service instance.

        Args:
            rollover_weeks: Minimum number of weeks that must elapse before a
                rollover is permitted. Defaults to four weeks.
            trigger_weekday: The weekday (``0`` = Monday … ``6`` = Sunday) on
                which a rollover may occur. Defaults to Sunday.
        """
        self._rollover_weeks = rollover_weeks
        self._trigger_weekday = trigger_weekday

    def check_and_rollover(self, active_plan: Dict[str, Any] | None, reference_date: date) -> bool:
        """Determine whether a new training cycle should start.

        Args:
            active_plan: The currently active training plan, or ``None`` if no
                plan is available.
            reference_date: The date to evaluate.

        Returns:
            ``True`` if rollover conditions are met, otherwise ``False``.
        """
        if not active_plan:
            return False

        start_date = active_plan.get("start_date")
        if start_date is None:
            return False

        days_into_plan = (reference_date - start_date).days
        if days_into_plan < 0:
            return False

        week_in_plan = (days_into_plan // 7) + 1

        return week_in_plan >= self._rollover_weeks and reference_date.weekday() == self._trigger_weekday

    def should_rollover(self, active_plan: Dict[str, Any] | None, reference_date: date) -> bool:
        """Backward compatible alias for :meth:`check_and_rollover`."""

        return self.check_and_rollover(active_plan, reference_date)
