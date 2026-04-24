"""Running planning utilities.

This module isolates running session construction from the strength plan builder
so it can evolve toward adaptive, goal-driven planning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List

from pete_e.domain import schedule_rules


@dataclass(frozen=True)
class RunningGoal:
    """Optional race goal inputs for future adaptive running logic."""

    target_race: str | None = None
    race_date: date | None = None
    target_time: str | None = None


class RunningPlanner:
    """Builds running sessions for each training week."""

    def build_week_sessions(
        self,
        *,
        week_number: int,
        goal: RunningGoal | None = None,
        health_metrics: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """Return running workouts for a given week.

        ``goal`` and ``health_metrics`` are accepted now so the calling code can
        pass richer context as the adaptive planning rules are expanded.
        """

        quality_details = (
            schedule_rules.quality_intervals_details()
            if week_number % 2 == 1
            else schedule_rules.quality_tempo_details()
        )

        # TODO: incorporate goal/health-driven adjustments when readiness and
        # completed session performance are threaded into plan generation.
        _ = (goal, health_metrics)

        long_run_distance = 6 + (week_number - 1)

        return [
            {
                "day_of_week": 1,
                "exercise_id": schedule_rules.RUN_CARDIO_EXERCISE_ID,
                "sets": 1,
                "reps": 1,
                "is_cardio": True,
                "comment": "Quality run",
                "details": quality_details,
            },
            {
                "day_of_week": 2,
                "exercise_id": schedule_rules.RUN_CARDIO_EXERCISE_ID,
                "sets": 1,
                "reps": 1,
                "is_cardio": True,
                "comment": "Easy run",
                "details": schedule_rules.easy_run_details(),
                "optional": True,
                "recovery_focused": True,
            },
            {
                "day_of_week": 4,
                "exercise_id": schedule_rules.RUN_CARDIO_EXERCISE_ID,
                "sets": 1,
                "reps": 1,
                "is_cardio": True,
                "comment": "Steady run",
                "details": schedule_rules.steady_run_details(),
            },
            {
                "day_of_week": 5,
                "exercise_id": schedule_rules.RUN_CARDIO_EXERCISE_ID,
                "sets": 1,
                "reps": 1,
                "is_cardio": True,
                "comment": "Recovery micro run",
                "details": schedule_rules.recovery_micro_run_details(),
                "optional": True,
                "recovery_focused": True,
            },
            {
                "day_of_week": 6,
                "exercise_id": schedule_rules.RUN_CARDIO_EXERCISE_ID,
                "sets": 1,
                "reps": 1,
                "is_cardio": True,
                "comment": "Long run",
                "details": schedule_rules.long_run_details(distance_km=long_run_distance),
            },
        ]
