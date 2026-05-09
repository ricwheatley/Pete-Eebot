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
    def save_withings_daily(
        self,
        day: date,
        weight_kg: Optional[float],
        body_fat_pct: Optional[float],
        muscle_pct: Optional[float],
        water_pct: Optional[float],
        *,
        fat_free_mass_kg: Optional[float] = None,
        fat_mass_kg: Optional[float] = None,
        muscle_mass_kg: Optional[float] = None,
        water_mass_kg: Optional[float] = None,
        bone_mass_kg: Optional[float] = None,
        visceral_fat_index: Optional[float] = None,
        bmr_kcal_day: Optional[float] = None,
        nerve_health_score_feet: Optional[float] = None,
        metabolic_age_years: Optional[float] = None,
    ) -> None:
        pass
        """Perform save withings daily."""

    @abstractmethod
    def save_withings_measure_groups(
        self,
        *,
        day: date,
        measure_groups: List[Dict[str, Any]],
    ) -> None:
        """Persist raw Withings measure groups for future-proof analysis."""
        pass

    @abstractmethod
    def save_wger_log(self, day: date, exercise_id: int, set_number: int,
                      reps: int, weight_kg: Optional[float], rir: Optional[float]) -> None:
        pass
        """Perform save wger log."""

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
        """Perform get daily summary."""

    @abstractmethod
    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        pass
        """Perform get historical metrics."""

    @abstractmethod
    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        pass
        """Perform get historical data."""

    def get_recent_running_workouts(
        self,
        *,
        days: int = 14,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        return []
        """Perform get recent running workouts."""

    def get_recent_strength_workouts(
        self,
        *,
        days: int = 14,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        return []
        """Perform get recent strength workouts."""

    def get_recent_strength_workload(
        self,
        *,
        days: int = 14,
        end_date: Optional[date] = None,
    ) -> float:
        workouts = self.get_recent_strength_workouts(days=days, end_date=end_date)
        total = 0.0
        for workout in workouts:
            if isinstance(workout, dict):
                total += float(workout.get("volume_kg", 0.0) or 0.0)
        return total
        """Perform get recent strength workload."""

    def get_latest_training_maxes(self) -> Dict[str, Optional[float]]:
        return {}
        """Perform get latest training maxes."""

    def get_recent_adherence_signal(
        self,
        *,
        days: int = 21,
        end_date: Optional[date] = None,
    ) -> Optional[float]:
        return None
        """Perform get recent adherence signal."""

    @abstractmethod
    def get_data_for_validation(self, week_start: date) -> Dict[str, Any]:
        """Return all data required for validation for the supplied week."""
        pass

    @abstractmethod
    def refresh_daily_summary(self, days: int = 7) -> None:
        pass
        """Perform refresh daily summary."""

    @abstractmethod
    def compute_body_age_for_date(self, target_date: date, *, birth_date: date) -> None:
        pass
        """Perform compute body age for date."""

    @abstractmethod
    def compute_body_age_for_range(
        self,
        start_date: date,
        end_date: date,
        *,
        birth_date: date,
    ) -> None:
        pass
        """Perform compute body age for range."""

    # -------------------------------------------------------------------------
    # Training plans
    # -------------------------------------------------------------------------
    @abstractmethod
    def save_training_plan(self, plan: dict, start_date: date) -> int:
        """Insert plan, weeks, workouts. Return plan_id."""
        pass

    @abstractmethod
    def has_any_plan(self) -> bool:
        pass
        """Perform has any plan."""

    @abstractmethod
    def get_plan(self, plan_id: int) -> Dict[str, Any]:
        pass
        """Perform get plan."""

    @abstractmethod
    def find_plan_by_start_date(self, start_date: date) -> Optional[Dict[str, Any]]:
        pass
        """Perform find plan by start date."""

    @abstractmethod
    def mark_plan_active(self, plan_id: int) -> None:
        pass
        """Perform mark plan active."""

    # -------------------------------------------------------------------------
    # Training cycles
    # -------------------------------------------------------------------------
    @abstractmethod
    def deactivate_active_training_cycles(self) -> None:
        pass
        """Perform deactivate active training cycles."""

    @abstractmethod
    def create_training_cycle(
        self,
        start_date: date,
        *,
        current_week: int,
        current_block: int,
    ) -> Dict[str, Any]:
        pass
        """Perform create training cycle."""

    @abstractmethod
    def get_active_training_cycle(self) -> Optional[Dict[str, Any]]:
        pass
        """Perform get active training cycle."""

    @abstractmethod
    def update_training_cycle_state(
        self,
        cycle_id: int,
        *,
        current_week: int,
        current_block: int,
    ) -> Optional[Dict[str, Any]]:
        pass
        """Perform update training cycle state."""

    # -------------------------------------------------------------------------
    # Muscle volume comparison
    # -------------------------------------------------------------------------
    @abstractmethod
    def get_plan_muscle_volume(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        pass
        """Perform get plan muscle volume."""

    @abstractmethod
    def get_actual_muscle_volume(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        pass
        """Perform get actual muscle volume."""

    # -------------------------------------------------------------------------
    # Active plan and plan weeks
    # ------------------------------------------------------------------------- 
    @abstractmethod
    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        pass
        """Perform get active plan."""

    @abstractmethod
    def get_plan_week_rows(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        pass
        """Perform get plan week rows."""

    @abstractmethod
    def update_workout_targets(self, updates: List[Dict[str, Any]]) -> None:
        pass
        """Perform update workout targets."""

    @abstractmethod
    def refresh_plan_view(self) -> None:
        pass
        """Perform refresh plan view."""

    @abstractmethod
    def refresh_actual_view(self) -> None:
        pass
        """Perform refresh actual view."""

    @abstractmethod
    def apply_plan_backoff(
        self,
        week_start_date: date,
        *,
        set_multiplier: float,
        rir_increment: int,
    ) -> None:
        pass
        """Perform apply plan backoff."""

    # -------------------------------------------------------------------------
    # Wger Catalog Upserts
    # -------------------------------------------------------------------------
    @abstractmethod
    def upsert_wger_categories(self, categories: List[Dict[str, Any]]) -> None:
        pass
        """Perform upsert wger categories."""

    @abstractmethod
    def upsert_wger_equipment(self, equipment: List[Dict[str, Any]]) -> None:
        pass
        """Perform upsert wger equipment."""

    @abstractmethod
    def upsert_wger_muscles(self, muscles: List[Dict[str, Any]]) -> None:
        pass
        """Perform upsert wger muscles."""

    @abstractmethod
    def upsert_wger_exercises(self, exercises: List[Dict[str, Any]]) -> None:
        pass
        """Perform upsert wger exercises."""

    # -------------------------------------------------------------------------
    # Validation logs
    # -------------------------------------------------------------------------
    @abstractmethod
    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        pass
        """Perform save validation log."""

    @abstractmethod
    def was_week_exported(self, plan_id: int, week_number: int) -> bool:
        pass
        """Perform was week exported."""

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
        """Perform record wger export."""
