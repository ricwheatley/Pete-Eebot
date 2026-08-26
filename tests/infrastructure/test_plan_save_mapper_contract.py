"""Mapper characterization at the full-plan save boundary."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from pete_e.application.services import PlanService
from pete_e.infrastructure.mappers import PlanMapper, PlanMappingError


def test_mapper_preserves_save_fields_and_its_precedence_rules() -> None:
    details = {"display_name": "Threshold run", "nested": {"laps": 4}}
    mapper = PlanMapper()

    plan = mapper.from_dict(
        {
            "start_date": date(2026, 8, 31),
            "metadata": {"source": "mapper-characterization"},
            "plan_weeks": [
                {
                    "week_number": "2",
                    "is_test": True,
                    "workouts": [
                        {
                            "id": "9",
                            "day_of_week": "3",
                            "slot": "semantic-slot",
                            "scheduled_time": "06:07:08",
                            "is_cardio": True,
                            "type": "tempo",
                            "percent_1rm": "82.5",
                            "intensity": "threshold",
                            "comment": 123,
                            "optional": "yes",
                            "recovery_focused": 1,
                            "details": details,
                            "programmed_difficulty": "6",
                            "exercise_id": None,
                            "exercise_name": "Run",
                            "sets": "4",
                            "reps": "8",
                            "rir": 2,
                            "rir_cue": 5,
                            "target_weight_kg": "91.25",
                            "muscle_group": "legs",
                        }
                    ],
                }
            ],
        }
    )
    payload = mapper.to_persistence_payload(plan)
    workout = payload["plan_weeks"][0]["workouts"][0]

    assert payload["start_date"] == date(2026, 8, 31)
    assert payload["weeks"] == 1
    assert payload["metadata"] == {"source": "mapper-characterization"}
    assert payload["plan_weeks"][0]["week_number"] == 2
    assert payload["plan_weeks"][0]["is_test"] is True
    assert workout == {
        "id": 9,
        "day_of_week": 3,
        "slot": "06:07:08",
        "scheduled_time": "06:07:08",
        "is_cardio": True,
        "type": "tempo",
        "percent_1rm": 82.5,
        "intensity": "threshold",
        "comment": "123",
        "optional": True,
        "recovery_focused": True,
        "details": details,
        "programmed_difficulty": 6,
        "exercise_id": None,
        "exercise_name": "Run",
        "sets": 4,
        "reps": 8,
        "rir": 2.0,
        "target_weight_kg": 91.25,
        "muscle_group": "legs",
    }


def test_mapper_failure_occurs_before_repository_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TrackingDal:
        def __init__(self) -> None:
            self.saved = False

        def get_latest_training_maxes(self) -> dict[str, float]:
            return {
                "squat": 180.0,
                "bench": 120.0,
                "deadlift": 220.0,
                "ohp": 70.0,
            }

        def get_historical_metrics(self, days: int) -> list[dict[str, Any]]:
            return []

        def get_recent_running_workouts(
            self,
            *,
            days: int,
            end_date: date,
        ) -> list[dict[str, Any]]:
            return []

        def save_full_plan(self, plan_dict: dict[str, Any]) -> int:
            self.saved = True
            return 1

    dal = TrackingDal()
    service = PlanService(dal=dal)  # type: ignore[arg-type]
    monkeypatch.setattr(
        service.factory,
        "create_unified_531_block_plan",
        lambda *args, **kwargs: {
            "start_date": date(2026, 8, 31),
            "metadata": ["invalid"],
            "plan_weeks": [{"week_number": 1, "workouts": []}],
        },
    )

    with pytest.raises(PlanMappingError, match="metadata must be a mapping"):
        service.create_and_persist_531_block(date(2026, 8, 31))

    assert dal.saved is False
