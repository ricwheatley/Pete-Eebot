"""Import completed wger strength sets needed by plan recalibration."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping

from pete_e.infrastructure import log_utils
from pete_e.utils.coercion import coerce_float, coerce_int


class WgerLogSyncService:
    """Normalize wger workout-log responses into the local strength log."""

    def __init__(self, *, dal: Any, client: Any):
        self.dal = dal
        self.client = client

    def sync(self, *, start_date: date, end_date: date) -> int:
        logs = self.client.get_workout_logs(start_date, end_date)
        saved = 0
        for workout in logs or []:
            if not isinstance(workout, Mapping):
                continue
            workout_date = self._date(workout.get("date"))
            if workout_date is None:
                continue
            for exercise_id, set_number, logged_set in self._sets(workout):
                reps = coerce_int(logged_set.get("repetitions") or logged_set.get("reps"))
                weight = coerce_float(logged_set.get("weight") or logged_set.get("weight_kg"))
                rir = coerce_float(logged_set.get("rir"))
                if exercise_id is None or reps is None or reps < 1:
                    continue
                self.dal.save_wger_log(
                    workout_date,
                    exercise_id,
                    set_number,
                    reps,
                    weight,
                    rir,
                )
                saved += 1
        log_utils.info(
            f"Imported {saved} completed strength set(s) from wger for "
            f"{start_date.isoformat()} through {end_date.isoformat()}."
        )
        return saved

    @classmethod
    def _sets(cls, workout: Mapping[str, Any]) -> Iterable[tuple[int | None, int, Mapping[str, Any]]]:
        entries = workout.get("entries")
        if not isinstance(entries, list):
            entries = [workout]
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            exercise = entry.get("exercise_id", entry.get("exercise"))
            if isinstance(exercise, Mapping):
                exercise = exercise.get("id")
            exercise_id = coerce_int(exercise)
            sets = entry.get("sets")
            if not isinstance(sets, list):
                sets = [entry]
            for index, logged_set in enumerate(sets, start=1):
                if not isinstance(logged_set, Mapping):
                    continue
                set_number = coerce_int(
                    logged_set.get("set_number") or logged_set.get("order")
                ) or index
                yield exercise_id, set_number, logged_set

    @staticmethod
    def _date(value: Any) -> date | None:
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None
