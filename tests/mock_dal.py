"""Utilities for constructing DataAccessLayer test doubles."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from pete_e.domain.data_access import DataAccessLayer
from pete_e.domain.validation import MAX_BASELINE_WINDOW_DAYS, resolve_plan_context


class MockableDal(DataAccessLayer):
    """Concrete DataAccessLayer with inert implementations.

    Tests can subclass this base and override only the behaviours that are
    relevant for the scenario under test. All other methods intentionally do
    nothing (or return empty placeholders) so that simple stubs automatically
    satisfy the interface even as it grows optional surface area.
    """

    # ------------------------------------------------------------------
    # Source saves
    # ------------------------------------------------------------------
    def save_withings_daily(
        self,
        day: date,
        weight_kg: Optional[float],
        body_fat_pct: Optional[float],
        muscle_pct: Optional[float],
        water_pct: Optional[float],
    ) -> None:
        pass

    def save_wger_log(
        self,
        day: date,
        exercise_id: int,
        set_number: int,
        reps: int,
        weight_kg: Optional[float],
        rir: Optional[float],
    ) -> None:
        pass

    def load_lift_log(
        self,
        exercise_ids: Optional[List[int]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        return {}

    # ------------------------------------------------------------------
    # Summaries (read-only views)
    # ------------------------------------------------------------------
    def get_daily_summary(self, target_date: date) -> Optional[Dict[str, Any]]:
        return None

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        return []

    def get_historical_data(
        self, start_date: date, end_date: date
    ) -> List[Dict[str, Any]]:
        return []

    def get_data_for_validation(self, week_start: date) -> Dict[str, Any]:
        observation_end = week_start - timedelta(days=1)
        baseline_start = observation_end - timedelta(days=MAX_BASELINE_WINDOW_DAYS - 1)
        previous_week_start = week_start - timedelta(days=7)
        previous_week_end = week_start - timedelta(days=1)

        plan_record = self.get_active_plan() or self.find_plan_by_start_date(week_start)
        plan_context = resolve_plan_context(plan_record, default_start=week_start)

        historical_rows = self.get_historical_data(baseline_start, observation_end) or []
        planned_rows: List[Dict[str, Any]] = []
        actual_rows: List[Dict[str, Any]] = []

        plan_payload: Optional[Dict[str, Any]] = None

        if plan_context:
            days_since_start = (week_start - plan_context.start_date).days
            if days_since_start >= 0:
                upcoming_week_number = (days_since_start // 7) + 1
                prior_week_number = upcoming_week_number - 1
                if prior_week_number > 0:
                    planned_rows = (
                        self.get_plan_muscle_volume(plan_context.plan_id, prior_week_number)
                        or []
                    )
                    actual_rows = (
                        self.get_actual_muscle_volume(previous_week_start, previous_week_end)
                        or []
                    )
                plan_payload = {
                    "plan_id": plan_context.plan_id,
                    "start_date": plan_context.start_date,
                    "upcoming_week_number": upcoming_week_number,
                    "prior_week_number": prior_week_number,
                    "prior_week_start": previous_week_start,
                    "prior_week_end": previous_week_end,
                }

        return {
            "plan": plan_payload,
            "historical_rows": historical_rows,
            "planned_rows": planned_rows,
            "actual_rows": actual_rows,
        }

    def refresh_daily_summary(self, days: int = 7) -> None:
        pass

    def compute_body_age_for_date(
        self,
        target_date: date,
        *,
        birth_date: date,
    ) -> None:
        pass

    def compute_body_age_for_range(
        self,
        start_date: date,
        end_date: date,
        *,
        birth_date: date,
    ) -> None:
        pass

    # ------------------------------------------------------------------
    # Training plans
    # ------------------------------------------------------------------
    def save_training_plan(self, plan: dict, start_date: date) -> int:
        return 0

    def has_any_plan(self) -> bool:
        return False

    def get_plan(self, plan_id: int) -> Dict[str, Any]:
        return {}

    def find_plan_by_start_date(
        self, start_date: date
    ) -> Optional[Dict[str, Any]]:
        return None

    def mark_plan_active(self, plan_id: int) -> None:
        pass

    def deactivate_active_training_cycles(self) -> None:
        pass

    def create_training_cycle(
        self,
        start_date: date,
        *,
        current_week: int,
        current_block: int,
    ) -> Dict[str, Any]:
        return {
            "id": 0,
            "start_date": start_date,
            "current_week": current_week,
            "current_block": current_block,
        }

    def get_active_training_cycle(self) -> Optional[Dict[str, Any]]:
        return None

    def update_training_cycle_state(
        self,
        cycle_id: int,
        *,
        current_week: int,
        current_block: int,
    ) -> Optional[Dict[str, Any]]:
        return None

    # ------------------------------------------------------------------
    # Muscle volume comparison
    # ------------------------------------------------------------------
    def get_plan_muscle_volume(
        self, plan_id: int, week_number: int
    ) -> List[Dict[str, Any]]:
        return []

    def get_actual_muscle_volume(
        self, start_date: date, end_date: date
    ) -> List[Dict[str, Any]]:
        return []

    # ------------------------------------------------------------------
    # Active plan and plan weeks
    # ------------------------------------------------------------------
    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        return None

    def get_plan_week(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        return []

    def update_workout_targets(self, updates: List[Dict[str, Any]]) -> None:
        pass

    def refresh_plan_view(self) -> None:
        pass

    def refresh_actual_view(self) -> None:
        pass

    def apply_plan_backoff(
        self,
        week_start_date: date,
        *,
        set_multiplier: float,
        rir_increment: int,
    ) -> None:
        pass

    # ------------------------------------------------------------------
    # Wger Catalog Upserts
    # ------------------------------------------------------------------
    def upsert_wger_categories(self, categories: List[Dict[str, Any]]) -> None:
        pass

    def upsert_wger_equipment(self, equipment: List[Dict[str, Any]]) -> None:
        pass

    def upsert_wger_muscles(self, muscles: List[Dict[str, Any]]) -> None:
        pass

    def upsert_wger_exercises(self, exercises: List[Dict[str, Any]]) -> None:
        pass

    # ------------------------------------------------------------------
    # Validation logs
    # ------------------------------------------------------------------
    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        pass

    def was_week_exported(self, plan_id: int, week_number: int) -> bool:
        return False

    def record_wger_export(
        self,
        plan_id: int,
        week_number: int,
        payload: Dict[str, Any],
        response: Optional[Dict[str, Any]] = None,
        routine_id: Optional[int] = None,
    ) -> None:
        pass
