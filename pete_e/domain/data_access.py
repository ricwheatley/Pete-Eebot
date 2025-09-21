# (Functional **interface**) Abstract DataAccessLayer (DB repository interface)

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
    def load_lift_log(
        self,
        exercise_ids: Optional[List[int]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Return lift log entries grouped by exercise id."""
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

    @abstractmethod
    def find_plan_by_start_date(self, start_date: date) -> Optional[Dict[str, Any]]:
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
    # Active plan and plan weeks
    # ------------------------------------------------------------------------- 
    @abstractmethod
    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_plan_week(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def update_workout_targets(self, updates: List[Dict[str, Any]]) -> None:
        pass

    @abstractmethod
    def refresh_plan_view(self) -> None:
        pass

    @abstractmethod
    def refresh_actual_view(self) -> None:
        pass

    # -------------------------------------------------------------------------
    # Wger Catalog Upserts
    # -------------------------------------------------------------------------
    @abstractmethod
    def upsert_wger_categories(self, categories: List[Dict[str, Any]]) -> None:
        pass

    @abstractmethod
    def upsert_wger_equipment(self, equipment: List[Dict[str, Any]]) -> None:
        pass

    @abstractmethod
    def upsert_wger_muscles(self, muscles: List[Dict[str, Any]]) -> None:
        pass

    @abstractmethod
    def upsert_wger_exercises(self, exercises: List[Dict[str, Any]]) -> None:
        pass

    # -------------------------------------------------------------------------
    # Validation logs
    # -------------------------------------------------------------------------
    @abstractmethod
    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        pass

    @abstractmethod
    def was_week_exported(self, plan_id: int, week_number: int) -> bool:
        pass

    @abstractmethod
    def record_wger_export(
        self,
        plan_id: int,
        week_number: int,
        payload: Dict[str, Any],
        response: Optional[Dict[str, Any]] = None,
        routine_id: Optional[int] = None,
    ) -> None:
        pass