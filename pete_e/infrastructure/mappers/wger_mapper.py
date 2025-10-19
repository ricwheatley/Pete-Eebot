"""Mapping utilities for converting domain plans to wger payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any, Dict, List

from pete_e.domain.entities import Plan, Week, Workout


class WgerMappingError(ValueError):
    """Raised when a domain plan cannot be converted into an API payload."""


@dataclass
class WgerPayloadMapper:
    """Create payloads understood by the wger API."""

    def build_week_payload(
        self,
        plan: Plan,
        week_number: int,
        *,
        plan_id: int | None = None,
    ) -> Dict[str, Any]:
        """Return a payload describing the workouts for ``week_number``."""

        week = self._find_week(plan, week_number)
        days: Dict[int, List[Dict[str, Any]]] = {}

        for workout in week.workouts:
            entry = self._workout_to_payload(workout)
            days.setdefault(workout.day_of_week, []).append(entry)

        ordered_days = [
            {"day_of_week": day, "exercises": days[day]}
            for day in sorted(days)
        ]

        payload: Dict[str, Any] = {
            "week_number": week.week_number,
            "days": ordered_days,
        }
        if plan_id is not None:
            payload["plan_id"] = plan_id
        if plan.start_date is not None:
            payload["plan_start_date"] = plan.start_date.isoformat()
        return payload

    def build_plan_payload(self, plan: Plan, *, plan_id: int | None = None) -> Dict[str, Any]:
        """Return a payload for all weeks in ``plan``."""

        payload = {
            "plan_id": plan_id,
            "plan_start_date": plan.start_date.isoformat() if plan.start_date else None,
            "weeks": [
                self.build_week_payload(plan, week.week_number, plan_id=plan_id)
                for week in sorted(plan.weeks, key=lambda w: w.week_number)
            ],
        }
        return payload

    def _find_week(self, plan: Plan, week_number: int) -> Week:
        for week in plan.weeks:
            if week.week_number == week_number:
                return week
        raise WgerMappingError(f"plan does not contain week {week_number}")

    def _workout_to_payload(self, workout: Workout) -> Dict[str, Any]:
        exercise = workout.exercise
        slot_value = workout.slot
        if isinstance(slot_value, time):
            slot_value = slot_value.strftime("%H:%M:%S")
        elif slot_value is not None:
            slot_value = str(slot_value)

        payload: Dict[str, Any] = {
            "is_cardio": workout.is_cardio,
            "type": workout.type,
            "day_of_week": workout.day_of_week,
            "slot": slot_value,
            "percent_1rm": workout.percent_1rm,
            "intensity": workout.intensity,
        }

        if exercise is not None:
            payload.update(
                {
                    "exercise": exercise.id,
                    "exercise_name": exercise.name,
                    "sets": exercise.sets,
                    "reps": exercise.reps,
                    "rir": exercise.rir,
                    "target_weight_kg": exercise.weight_target,
                    "muscle_group": exercise.muscle_group,
                }
            )
        return payload
