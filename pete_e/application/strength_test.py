"""Strength-test evaluation helpers used to refresh training maxes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping

from pete_e.domain import schedule_rules
from pete_e.infrastructure import log_utils
from pete_e.infrastructure.postgres_dal import PostgresDal

AMRAP_EPLEY_SOURCE = "AMRAP_EPLEY"
MAX_REASONABLE_AMRAP_REPS = 20


@dataclass(frozen=True)
class StrengthTestEvaluationResult:
    """Summary of a completed strength-test recalibration pass."""

    plan_id: int
    week_number: int
    week_start: date
    week_end: date
    lifts_updated: int


@dataclass(frozen=True)
class _LoggedSet:
    test_date: date
    reps: int
    weight_kg: float
    e1rm_kg: float
    """Represent LoggedSet."""


class StrengthTestService:
    """Convert logged AMRAP strength-test results into new training maxes."""

    def __init__(self, dal: PostgresDal):
        self.dal = dal
        """Initialize this object."""

    def evaluate_latest_test_week_and_update_tms(self) -> StrengthTestEvaluationResult | None:
        """Evaluate the latest test week, if available, and upsert training maxes."""

        required_methods = (
            "get_latest_test_week",
            "get_plan_week_rows",
            "load_lift_log",
            "insert_strength_test_result",
            "upsert_training_max",
        )
        missing_methods = [
            name for name in required_methods if not callable(getattr(self.dal, name, None))
        ]
        if missing_methods:
            log_utils.warn(
                "Strength-test recalibration skipped because the DAL is missing: "
                + ", ".join(sorted(missing_methods))
            )
            return None

        latest_test_week = self.dal.get_latest_test_week()
        if not latest_test_week:
            log_utils.info("No strength test week found; leaving training maxes unchanged.")
            return None

        plan_id = self._coerce_int(latest_test_week.get("plan_id"))
        week_number = self._coerce_int(latest_test_week.get("week_number")) or 1
        plan_start = self._coerce_date(latest_test_week.get("start_date"))
        if plan_id is None or plan_start is None:
            raise ValueError("Latest strength test week is missing plan metadata.")

        week_start = plan_start + timedelta(days=(week_number - 1) * 7)
        week_end = week_start + timedelta(days=6)

        plan_rows = self.dal.get_plan_week_rows(plan_id, week_number)
        planned_test_dates = self._planned_test_dates(plan_rows, week_start)
        logs_by_exercise = self.dal.load_lift_log(
            list(schedule_rules.TEST_WEEK_LIFT_ORDER),
            start_date=week_start,
            end_date=week_end,
        )

        lifts_updated = 0
        for exercise_id in schedule_rules.TEST_WEEK_LIFT_ORDER:
            planned_date = planned_test_dates.get(exercise_id)
            candidate = self._best_logged_set(
                logs_by_exercise.get(str(exercise_id), []),
                planned_test_date=planned_date,
            )
            if candidate is None:
                continue

            lift_code = schedule_rules.LIFT_CODE_BY_ID.get(exercise_id)
            if not lift_code:
                continue

            tm_kg = self._round_to_2p5(candidate.e1rm_kg * 0.90)
            self.dal.insert_strength_test_result(
                plan_id=plan_id,
                week_number=week_number,
                lift_code=lift_code,
                test_date=candidate.test_date,
                test_reps=candidate.reps,
                test_weight_kg=candidate.weight_kg,
                e1rm_kg=round(candidate.e1rm_kg, 1),
                tm_kg=tm_kg,
            )
            self.dal.upsert_training_max(
                lift_code=lift_code,
                tm_kg=tm_kg,
                measured_at=week_end,
                source=AMRAP_EPLEY_SOURCE,
            )
            lifts_updated += 1

        log_utils.info(
            "Strength-test recalibration finished for "
            f"plan {plan_id}, week {week_number}: updated {lifts_updated} lift(s)."
        )
        return StrengthTestEvaluationResult(
            plan_id=plan_id,
            week_number=week_number,
            week_start=week_start,
            week_end=week_end,
            lifts_updated=lifts_updated,
        )

    def _planned_test_dates(
        self,
        rows: Iterable[Mapping[str, Any]],
        week_start: date,
    ) -> dict[int, date]:
        planned: dict[int, date] = {}
        for row in rows:
            exercise_id = self._coerce_int(row.get("exercise_id"))
            day_of_week = self._coerce_int(row.get("day_of_week"))
            if exercise_id not in schedule_rules.TEST_WEEK_LIFT_ORDER or day_of_week is None:
                continue
            planned[exercise_id] = week_start + timedelta(days=day_of_week - 1)
        return planned
        """Perform planned test dates."""

    def _best_logged_set(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        planned_test_date: date | None,
    ) -> _LoggedSet | None:
        candidates: list[_LoggedSet] = []
        for row in rows:
            logged_set = self._row_to_logged_set(row)
            if logged_set is not None:
                candidates.append(logged_set)

        if not candidates:
            return None

        if planned_test_date is not None:
            exact_day_candidates = [
                candidate for candidate in candidates if candidate.test_date == planned_test_date
            ]
            if exact_day_candidates:
                candidates = exact_day_candidates

        return max(candidates, key=lambda item: (item.e1rm_kg, item.weight_kg, item.reps))
        """Perform best logged set."""

    def _row_to_logged_set(self, row: Mapping[str, Any]) -> _LoggedSet | None:
        test_date = self._coerce_date(row.get("date"))
        reps = self._coerce_int(row.get("reps"))
        weight_kg = self._coerce_float(row.get("weight_kg"))
        if test_date is None or reps is None or weight_kg is None:
            return None
        if reps < 1 or reps > MAX_REASONABLE_AMRAP_REPS or weight_kg <= 0:
            return None
        return _LoggedSet(
            test_date=test_date,
            reps=reps,
            weight_kg=weight_kg,
            e1rm_kg=self._e1rm_epley(weight_kg, reps),
        )
        """Perform row to logged set."""

    @staticmethod
    def _round_to_2p5(value: float) -> float:
        return round(value / 2.5) * 2.5
        """Perform round to 2p5."""

    @staticmethod
    def _e1rm_epley(weight_kg: float, reps: int) -> float:
        return weight_kg * (1.0 + reps / 30.0)
        """Perform e1rm epley."""

    @staticmethod
    def _coerce_date(value: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None
        """Perform coerce date."""

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
        """Perform coerce int."""

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
        """Perform coerce float."""
