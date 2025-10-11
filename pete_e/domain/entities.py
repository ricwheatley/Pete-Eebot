"""Domain entities representing training plans and workouts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import mean
from typing import Iterable, Mapping, MutableMapping, Sequence

from pete_e.domain.configuration import get_settings
from pete_e.utils import converters
from pete_e.utils import math as math_utils


def _metric_values(metrics: Sequence[Mapping[str, object]], key: str) -> list[float]:
    values: list[float] = []
    for metric in metrics:
        value = metric.get(key)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


@dataclass
class Exercise:
    """Single exercise performed within a workout."""

    id: int | None
    name: str
    sets: int | None = None
    reps: int | None = None
    rir: float | None = None
    weight_target: float | None = None
    muscle_group: str | None = None

    def apply_progression(
        self,
        history_entries: Sequence[Mapping[str, object]],
        *,
        recovery_good: bool,
    ) -> str:
        """Update the exercise's weight target based on progression rules."""

        history = list(history_entries)
        target_display = self.weight_target or 0.0

        if not history:
            detail = f"no RIR, recovery {'good' if recovery_good else 'poor'}"
            return (
                f"{self.name}: no history, kept at {target_display}kg ({detail})"
            )

        recent_entries = history[-4:]
        weights = [
            converters.to_float(entry.get("weight"))
            for entry in recent_entries
            if entry.get("weight") is not None
        ]
        weights = [w for w in weights if w is not None]

        rirs = [
            converters.to_float(entry.get("rir"))
            for entry in recent_entries
            if entry.get("rir") is not None
        ]
        rirs = [r for r in rirs if r is not None]

        if not weights:
            detail = f"no RIR, recovery {'good' if recovery_good else 'poor'}"
            return (
                f"{self.name}: no valid weight data, kept at {target_display}kg ({detail})"
            )

        avg_weight = mean(weights)
        use_rir = bool(rirs)
        avg_rir = mean(rirs) if use_rir else None

        target = self.weight_target if self.weight_target is not None else avg_weight
        domain_settings = get_settings()
        inc = domain_settings.progression_increment
        dec = domain_settings.progression_decrement

        if use_rir:
            if avg_rir is not None and avg_rir <= 1:
                inc += domain_settings.progression_increment / 2
            elif avg_rir is not None and avg_rir >= 2:
                inc /= 2

        if not recovery_good:
            inc /= 2
            dec *= 1.5

        detail = (
            f"avg RIR {avg_rir:.1f}" if use_rir and avg_rir is not None else "no RIR"
        ) + f", recovery {'good' if recovery_good else 'poor'}"

        new_target: float | None = None
        message: str

        if avg_weight >= target and (
            not use_rir or (avg_rir is not None and avg_rir <= 2)
        ):
            new_target = round(target * (1 + inc), 2)
            message = f"{self.name}: +{inc*100:.1f}% ({detail})"
        elif avg_weight < target or (
            use_rir and avg_rir is not None and avg_rir > 2
        ):
            new_target = round(target * (1 - dec), 2)
            message = f"{self.name}: -{dec*100:.1f}% ({detail})"
        else:
            message = f"{self.name}: no change ({detail})"

        if new_target is not None:
            self.weight_target = new_target

        return message


@dataclass
class Workout:
    """A scheduled workout within a training week."""

    id: int | None
    day_of_week: int
    slot: str | None = None
    is_cardio: bool = False
    type: str = "weights"
    percent_1rm: float | None = None
    exercise: Exercise | None = None
    intensity: str | None = None

    def is_weights_session(self) -> bool:
        return not self.is_cardio and self.type == "weights"

    def apply_progression(
        self,
        lift_history: Mapping[str, Sequence[Mapping[str, object]]],
        *,
        recovery_good: bool,
    ) -> list[str]:
        """Apply progression to each exercise belonging to this workout."""

        if not self.is_weights_session() or self.exercise is None:
            return []

        exercise_id = self.exercise.id
        if exercise_id is None:
            entries: Sequence[Mapping[str, object]] = []
        else:
            entries = lift_history.get(str(exercise_id), [])

        note = self.exercise.apply_progression(entries, recovery_good=recovery_good)
        return [note]

    @property
    def weight_target(self) -> float | None:
        return self.exercise.weight_target if self.exercise else None


@dataclass
class Week:
    """A training week containing multiple workouts."""

    week_number: int
    start_date: date | None = None
    workouts: list[Workout] = field(default_factory=list)

    def weights_workouts(self) -> Iterable[Workout]:
        for workout in self.workouts:
            if workout.is_weights_session():
                yield workout

    def apply_progression(
        self,
        lift_history: Mapping[str, Sequence[Mapping[str, object]]],
        *,
        recovery_good: bool,
    ) -> list[str]:
        """Apply progression across all relevant workouts."""

        notes: list[str] = []
        for workout in self.weights_workouts():
            notes.extend(
                workout.apply_progression(
                    lift_history,
                    recovery_good=recovery_good,
                )
            )
        return notes


@dataclass
class Plan:
    """Structured training plan consisting of multiple weeks."""

    start_date: date | None = None
    weeks: list[Week] = field(default_factory=list)
    metadata: MutableMapping[str, object] | None = None

    def muscle_totals(
        self,
        *,
        required_groups: Iterable[str],
    ) -> Mapping[str, float]:
        totals: dict[str, float] = {}
        for week in self.weeks:
            for workout in week.workouts:
                if workout.exercise is None:
                    continue
                muscle_group = workout.exercise.muscle_group
                if muscle_group is None:
                    continue
                sets = workout.exercise.sets
                if sets is None:
                    continue
                totals[muscle_group] = totals.get(muscle_group, 0.0) + float(sets)

        for group in required_groups:
            totals.setdefault(group, 0.0)
        return totals


def compute_recovery_flag(
    metrics_7d: Sequence[Mapping[str, object]],
    metrics_baseline: Sequence[Mapping[str, object]],
) -> bool:
    """Return True when recovery markers are within the expected range."""

    rhr_7 = math_utils.mean_or_none(_metric_values(metrics_7d, "hr_resting"))
    sleep_7 = math_utils.mean_or_none(
        _metric_values(metrics_7d, "sleep_asleep_minutes")
    )
    rhr_baseline = math_utils.mean_or_none(
        _metric_values(metrics_baseline, "hr_resting")
    )
    sleep_baseline = math_utils.mean_or_none(
        _metric_values(metrics_baseline, "sleep_asleep_minutes")
    )

    if (
        rhr_baseline is None
        or rhr_7 is None
        or sleep_baseline is None
        or sleep_7 is None
    ):
        return True

    domain_settings = get_settings()
    rhr_limit = rhr_baseline * (1 + domain_settings.rhr_allowed_increase)
    sleep_limit = sleep_baseline * domain_settings.sleep_allowed_decrease
    if rhr_7 > rhr_limit or sleep_7 < sleep_limit:
        return False
    return True
