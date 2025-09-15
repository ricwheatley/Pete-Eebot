from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from datetime import date


class DataAccessLayer(ABC):
    """
    Abstract Base Class for Pete-Eebot's PostgreSQL Data Access Layer.
    Defines clean, DB-native operations for all sources and derived data.
    """

    # -------------------------------------------------------------------------
    # Source saves
    # -------------------------------------------------------------------------
    @abstractmethod
    def save_withings_daily(self, day: date, weight_kg: float, body_fat_pct: float) -> None:
        pass

    @abstractmethod
    def save_apple_daily(self, day: date, metrics: Dict[str, Any]) -> None:
        """metrics dict should contain steps, exercise_minutes, calories, HR, sleep, etc."""
        pass

    @abstractmethod
    def save_wger_log(self, day: date, exercise_id: int, set_number: int,
                      reps: int, weight_kg: Optional[float], rir: Optional[float]) -> None:
        pass

    @abstractmethod
    def save_body_age_daily(self, day: date, metrics: Dict[str, Any]) -> None:
        pass

    # -------------------------------------------------------------------------
    # Summaries (read-only views)
    # -------------------------------------------------------------------------
    @abstractmethod
    def get_daily_summary(self, target_date: date) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        pass

    # -------------------------------------------------------------------------
    # Training plans
    # -------------------------------------------------------------------------
    @abstractmethod
    def save_training_plan(self, plan: dict, start_date: date) -> int:
        """Insert plan, weeks, workouts. Return plan_id."""
        pass

    @abstractmethod
    def get_plan(self, plan_id: int) -> Dict[str, Any]:
        pass

    # -------------------------------------------------------------------------
    # Muscle volume comparison
    # -------------------------------------------------------------------------
    @abstractmethod
    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        pass

    # -------------------------------------------------------------------------
    # Validation logs
    # -------------------------------------------------------------------------
    @abstractmethod
    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        pass
