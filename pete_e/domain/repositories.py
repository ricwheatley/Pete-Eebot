from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class PlanRepository(ABC):
    """Abstract interface for plan-related persistence operations."""

    @abstractmethod
    def get_latest_training_maxes(self) -> Dict[str, Optional[float]]:
        """Return the latest recorded training max values by lift name."""

    @abstractmethod
    def save_full_plan(self, plan_dict: Dict[str, Any]) -> int:
        """Persist a plan and return its identifier."""

    @abstractmethod
    def get_assistance_pool_for(self, main_lift_id: int) -> List[int]:
        """Return IDs of assistance lifts associated with the given main lift."""

    @abstractmethod
    def get_core_pool_ids(self) -> List[int]:
        """Return IDs of available core exercises."""
