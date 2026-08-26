from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Dict, List, Optional


class PlanRepository(ABC):
    """Abstract interface for plan-related persistence operations."""

    @abstractmethod
    def get_latest_training_maxes(self) -> Dict[str, Optional[float]]:
        """Return the latest recorded training max values by lift name."""

    @abstractmethod
    def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:
        """Atomically replace the active plan and return the new integer ID.

        Implementations preserve the legacy plan dictionary contract and
        propagate validation, mapping, and persistence failures to the caller.
        """

    @abstractmethod
    def get_assistance_pool_for(self, main_lift_id: int) -> List[int]:
        """Return IDs of assistance lifts associated with the given main lift."""

    @abstractmethod
    def get_core_pool_ids(self) -> List[int]:
        """Return IDs of available core exercises."""

    def get_exercise_difficulty_cap(
        self, as_of_date: date | None = None
    ) -> Dict[str, Any]:
        """Return the currently allowed exercise difficulty cap."""

        return {
            "current_cap": 2,
            "source": "repository-default",
            "evidence": {"available": False},
        }

    def get_assistance_candidates_for(
        self,
        main_lift_id: int,
        *,
        max_difficulty: int,
    ) -> List[Dict[str, Any]]:
        """Return assistance candidates with difficulty metadata."""

        return [
            {"exercise_id": exercise_id, "difficulty": None}
            for exercise_id in self.get_assistance_pool_for(main_lift_id)
        ]

    def get_core_candidates(self, *, max_difficulty: int) -> List[Dict[str, Any]]:
        """Return core candidates with difficulty metadata."""

        return [
            {"exercise_id": exercise_id, "difficulty": None}
            for exercise_id in self.get_core_pool_ids()
        ]
