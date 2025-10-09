"""Domain service encapsulating cycle rollover logic."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict


class CycleService:
    """Provides domain logic related to training cycle transitions."""

    @staticmethod
    def should_rollover(active_plan: Dict[str, Any], reference_date: date) -> bool:
        """Determine whether a new training cycle should start.

        Args:
            active_plan: The currently active training plan.
            reference_date: The date to use when evaluating rollover conditions.

        Returns:
            True if a rollover should occur, False otherwise.
        """
        if not active_plan:
            return False

        start_date = active_plan["start_date"]
        days_into_plan = (reference_date - start_date).days
        week_in_plan = (days_into_plan // 7) + 1

        return week_in_plan >= 4 and reference_date.weekday() == 6
