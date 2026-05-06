"""Mapping utilities for converting between persistence rows and domain plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from pete_e.domain import schedule_rules
from pete_e.domain.entities import Exercise, Plan, Week, Workout
from pete_e.utils import converters


class PlanMappingError(ValueError):
    """Raised when a persistence payload cannot be converted to a Plan."""


@dataclass
class PlanMapper:
    """Translate between persistence-layer representations and ``Plan`` objects."""

    def from_rows(
        self,
        plan_row: Mapping[str, Any],
        workout_rows: Sequence[Mapping[str, Any]],
    ) -> Plan:
        """Build a :class:`Plan` from database rows."""

        if plan_row is None:
            raise PlanMappingError("plan_row is required")

        start_date = self._to_date(plan_row.get("start_date"))
        if plan_row.get("start_date") is not None and start_date is None:
            raise PlanMappingError("start_date must be a valid date")

        metadata = self._validate_metadata(plan_row.get("metadata"))

        weeks: dict[int, Week] = {}
        for row in workout_rows:
            if not isinstance(row, Mapping):
                raise PlanMappingError("workout rows must be mappings")

            week_number = self._to_int(row.get("week_number"))
            if week_number is None:
                raise PlanMappingError("week_number is required for each workout row")

            week = weeks.get(week_number)
            if week is None:
                week_start_date = self._to_date(row.get("week_start_date"))
                week = Week(week_number=week_number, start_date=week_start_date, workouts=[])
                weeks[week_number] = week

            week.workouts.append(self._build_workout(row))

        ordered_weeks = [weeks[number] for number in sorted(weeks)]
        return Plan(start_date=start_date, weeks=ordered_weeks, metadata=metadata)

    def from_dict(self, payload: Mapping[str, Any]) -> Plan:
        """Construct a :class:`Plan` from the plan dictionaries used by the DAL."""

        if payload is None:
            raise PlanMappingError("payload is required")

        start_date = self._to_date(payload.get("start_date"))
        if payload.get("start_date") is not None and start_date is None:
            raise PlanMappingError("start_date must be a valid date")

        metadata = self._validate_metadata(payload.get("metadata"))

        weeks_payload = self._iter_week_payloads(payload)
        weeks = [self._build_week(week_payload) for week_payload in weeks_payload]
        weeks.sort(key=lambda w: w.week_number)

        return Plan(start_date=start_date, weeks=weeks, metadata=metadata)

    def to_persistence_payload(self, plan: Plan) -> dict[str, Any]:
        """Convert a domain :class:`Plan` into the structure expected by the DAL."""

        payload: dict[str, Any] = {
            "start_date": plan.start_date,
            "weeks": len(plan.weeks),
            "plan_weeks": [],
        }

        if plan.metadata is not None:
            payload["metadata"] = dict(plan.metadata)

        for week in plan.weeks:
            workouts_payload: list[dict[str, Any]] = []
            for workout in week.workouts:
                workouts_payload.append(self._workout_to_payload(workout))

            payload["plan_weeks"].append(
                {
                    "week_number": week.week_number,
                    "start_date": week.start_date,
                    "workouts": workouts_payload,
                }
            )

        return payload

    # --- helpers -----------------------------------------------------------------

    def _build_week(self, payload: Mapping[str, Any]) -> Week:
        week_number = self._to_int(payload.get("week_number"))
        if week_number is None:
            raise PlanMappingError("week_number is required for each week payload")

        start_date = self._to_date(payload.get("start_date"))

        workouts_payload = payload.get("workouts")
        if workouts_payload is None:
            workouts_payload = []
        if not isinstance(workouts_payload, Iterable):
            raise PlanMappingError("workouts must be an iterable")

        workouts = [self._build_workout(item) for item in workouts_payload]

        return Week(week_number=week_number, start_date=start_date, workouts=workouts)
        """Perform build week."""

    def _build_workout(self, data: Mapping[str, Any]) -> Workout:
        day_of_week = self._to_int(data.get("day_of_week"))
        if day_of_week is None:
            raise PlanMappingError("day_of_week is required for each workout")

        workout_id = self._to_int(data.get("id"))
        scheduled_time = self._to_time_string(data.get("scheduled_time"))
        slot = scheduled_time or data.get("slot")
        is_cardio = bool(data.get("is_cardio"))
        details_raw = data.get("details")
        details: MutableMapping[str, Any] | None = None
        if isinstance(details_raw, MutableMapping):
            details = dict(details_raw)
        workout_type = data.get("type")
        if workout_type is None:
            session_type = str((details or {}).get("session_type") or "").strip().lower()
            if session_type == schedule_rules.STRETCH_SESSION_TYPE:
                workout_type = schedule_rules.MOBILITY_WORKOUT_TYPE
            else:
                workout_type = "cardio" if is_cardio else "weights"
        percent_1rm = converters.to_float(data.get("percent_1rm"))
        intensity = data.get("intensity")
        comment = data.get("comment")
        optional = bool(data.get("optional", False))
        recovery_focused = bool(data.get("recovery_focused", False))

        exercise = self._build_exercise(data)

        return Workout(
            id=workout_id,
            day_of_week=day_of_week,
            slot=slot,
            is_cardio=is_cardio,
            type=str(workout_type),
            percent_1rm=percent_1rm,
            exercise=exercise,
            intensity=intensity,
            comment=None if comment is None else str(comment),
            optional=optional,
            recovery_focused=recovery_focused,
            details=details,
        )
        """Perform build workout."""

    def _build_exercise(self, data: Mapping[str, Any]) -> Exercise | None:
        exercise_id = self._to_int(data.get("exercise_id"))
        exercise_name = data.get("exercise_name")
        details_raw = data.get("details")
        details = details_raw if isinstance(details_raw, Mapping) else None
        if exercise_name is None and details is not None:
            display_name = details.get("display_name")
            if display_name:
                exercise_name = display_name

        if exercise_id is None and exercise_name is None and data.get("is_cardio"):
            return Exercise(id=None, name="Cardio", sets=None, reps=None)

        if exercise_id is None and exercise_name is None:
            return None

        rir_value = data.get("rir")
        if rir_value is None:
            rir_value = data.get("rir_cue")

        sets = self._to_int(data.get("sets"))
        reps = self._to_int(data.get("reps"))
        weight_target = converters.to_float(data.get("target_weight_kg"))

        name = (
            str(exercise_name)
            if exercise_name is not None
            else f"Exercise #{exercise_id}" if exercise_id is not None
            else "Exercise"
        )

        muscle_group = data.get("muscle_group")

        return Exercise(
            id=exercise_id,
            name=name,
            sets=sets,
            reps=reps,
            rir=converters.to_float(rir_value),
            weight_target=weight_target,
            muscle_group=muscle_group,
        )
        """Perform build exercise."""

    def _iter_week_payloads(self, payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        weeks = payload.get("plan_weeks")
        if isinstance(weeks, list):
            return weeks

        weeks_alt = payload.get("weeks")
        if isinstance(weeks_alt, list):
            return weeks_alt

        return []
        """Perform iter week payloads."""

    def _workout_to_payload(self, workout: Workout) -> dict[str, Any]:
        exercise = workout.exercise
        scheduled_time = self._to_time_string(workout.slot)
        payload: dict[str, Any] = {
            "id": workout.id,
            "day_of_week": workout.day_of_week,
            "slot": workout.slot,
            "scheduled_time": scheduled_time,
            "is_cardio": workout.is_cardio,
            "type": workout.type,
            "percent_1rm": workout.percent_1rm,
            "intensity": workout.intensity,
            "comment": workout.comment,
            "optional": workout.optional,
            "recovery_focused": workout.recovery_focused,
            "details": None if workout.details is None else dict(workout.details),
        }

        if exercise is not None:
            payload.update(
                {
                    "exercise_id": exercise.id,
                    "exercise_name": exercise.name,
                    "sets": exercise.sets,
                    "reps": exercise.reps,
                    "rir": exercise.rir,
                    "target_weight_kg": exercise.weight_target,
                    "muscle_group": exercise.muscle_group,
                }
            )
        return payload
        """Perform workout to payload."""

    def _to_int(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
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
                except ValueError as exc:  # pragma: no cover - defensive
                    raise PlanMappingError(f"Cannot convert '{value}' to int") from exc
        raise PlanMappingError(f"Cannot convert type {type(value)!r} to int")
        """Perform to int."""

    def _to_date(self, value: Any) -> date | None:
        return converters.to_date(value)
        """Perform to date."""

    def _to_time_string(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, time):
            return value.strftime("%H:%M:%S")
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = time.fromisoformat(text)
        except ValueError:
            return None
        return parsed.strftime("%H:%M:%S")
        """Perform to time string."""

    def _validate_metadata(self, metadata: Any) -> MutableMapping[str, Any] | None:
        if metadata is None:
            return None
        if isinstance(metadata, MutableMapping):
            return metadata
        raise PlanMappingError("metadata must be a mapping when provided")
        """Perform validate metadata."""
