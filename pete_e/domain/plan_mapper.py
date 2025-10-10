"""Mapping utilities for converting plan payloads to domain entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from pete_e.domain.entities import Exercise, Plan, Week, Workout
from pete_e.utils import converters


@dataclass
class PlanMapper:
    """Translate between persisted plan representations and domain entities."""

    def to_entity(self, payload: Dict[str, Any]) -> Plan:
        start_date = converters.to_date(payload.get("start_date"))
        weeks_data = self._extract_weeks(payload)

        weeks: List[Week] = []
        for week_data in weeks_data:
            weeks.append(self._build_week(week_data))

        metadata = payload.get("metadata")
        metadata_dict = metadata if isinstance(metadata, dict) else None
        return Plan(start_date=start_date, weeks=weeks, metadata=metadata_dict)

    def to_payload(self, plan: Plan) -> Dict[str, Any]:
        weeks_payload: List[Dict[str, Any]] = []
        for week in plan.weeks:
            workouts_payload: List[Dict[str, Any]] = []
            for workout in week.workouts:
                exercise = workout.exercise
                workouts_payload.append(
                    {
                        "id": workout.id,
                        "day_of_week": workout.day_of_week,
                        "slot": workout.slot,
                        "is_cardio": workout.is_cardio,
                        "type": workout.type,
                        "percent_1rm": workout.percent_1rm,
                        "intensity": workout.intensity,
                        "exercise_id": exercise.id if exercise else None,
                        "exercise_name": exercise.name if exercise else None,
                        "sets": exercise.sets if exercise else None,
                        "reps": exercise.reps if exercise else None,
                        "rir": exercise.rir if exercise else None,
                        "target_weight_kg": exercise.weight_target if exercise else None,
                        "muscle_group": exercise.muscle_group if exercise else None,
                    }
                )

            weeks_payload.append(
                {
                    "week_number": week.week_number,
                    "start_date": week.start_date,
                    "workouts": workouts_payload,
                }
            )

        payload: Dict[str, Any] = {
            "start_date": plan.start_date,
            "weeks": len(plan.weeks),
            "plan_weeks": weeks_payload,
        }
        if plan.metadata is not None:
            payload["metadata"] = dict(plan.metadata)
        return payload

    def _extract_weeks(self, payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        weeks = payload.get("plan_weeks")
        if isinstance(weeks, list):
            return weeks
        weeks_alt = payload.get("weeks")
        if isinstance(weeks_alt, list):
            return weeks_alt
        return []

    def _build_week(self, data: Dict[str, Any]) -> Week:
        week_number = self._to_int(data.get("week_number")) or 0
        start_date = converters.to_date(data.get("start_date"))
        workouts_data = data.get("workouts")
        workouts: List[Workout] = []

        if isinstance(workouts_data, list):
            for item in workouts_data:
                if not isinstance(item, dict):
                    continue
                workouts.append(self._build_workout(item))

        return Week(week_number=week_number, start_date=start_date, workouts=workouts)

    def _build_workout(self, data: Dict[str, Any]) -> Workout:
        workout_id = self._to_int(data.get("id"))
        day_of_week = self._to_int(data.get("day_of_week")) or 0
        is_cardio = bool(data.get("is_cardio"))
        workout_type = data.get("type") or ("cardio" if is_cardio else "weights")
        percent = converters.to_float(data.get("percent_1rm"))
        slot = data.get("slot")
        intensity = data.get("intensity")

        exercise = self._build_exercise(data)

        return Workout(
            id=workout_id,
            day_of_week=day_of_week,
            slot=slot,
            is_cardio=is_cardio,
            type=str(workout_type),
            percent_1rm=percent,
            exercise=exercise,
            intensity=intensity,
        )

    def _build_exercise(self, data: Dict[str, Any]) -> Exercise | None:
        exercise_id = self._to_int(data.get("exercise_id"))
        name = data.get("exercise_name")
        if exercise_id is None and name is None:
            return None

        rir_value = data.get("rir")
        if rir_value is None:
            rir_value = data.get("rir_cue")

        return Exercise(
            id=exercise_id,
            name=str(name) if name is not None else f"Exercise #{exercise_id}",
            sets=self._to_int(data.get("sets")),
            reps=self._to_int(data.get("reps")),
            rir=converters.to_float(rir_value),
            weight_target=converters.to_float(data.get("target_weight_kg")),
            muscle_group=data.get("muscle_group"),
        )

    def _to_int(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return int(stripped)
            except ValueError:
                try:
                    return int(float(stripped))
                except ValueError:
                    return None
        return None
