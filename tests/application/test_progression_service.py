from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

from pete_e.application.progression_service import ProgressionService
from pete_e.domain.progression import PlanProgressionDecision, WorkoutProgression


@dataclass
class StubDal:
    plan_rows: List[Dict[str, Any]]
    lift_history: Dict[str, List[Dict[str, Any]]]
    recent_metrics: List[Dict[str, Any]]
    baseline_metrics: List[Dict[str, Any]]

    def __post_init__(self) -> None:
        self.updated_targets: List[List[Dict[str, Any]]] = []
        self.refresh_calls: int = 0
        self.loaded_ids: List[List[int]] = []

    def get_plan_week(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:  # noqa: ARG002
        return list(self.plan_rows)

    def load_lift_log(self, exercise_ids: List[int]) -> Dict[str, Any]:
        self.loaded_ids.append(list(exercise_ids))
        return self.lift_history

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        if days == 7:
            return self.recent_metrics
        return self.baseline_metrics

    def update_workout_targets(self, updates: List[Dict[str, Any]]) -> None:
        self.updated_targets.append(updates)

    def refresh_plan_view(self) -> None:
        self.refresh_calls += 1


def _make_plan_rows() -> List[Dict[str, Any]]:
    return [
        {
            "id": 2001,
            "exercise_id": 501,
            "day_of_week": 1,
            "sets": 5,
            "reps": 5,
            "rir": 1,
            "target_weight_kg": 100.0,
            "exercise_name": "Back Squat",
            "is_cardio": False,
        }
    ]


def test_calibrate_plan_week_fetches_and_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    plan_rows = _make_plan_rows()
    lift_history = {"501": [{"weight": 100.0, "rir": 1.0} for _ in range(4)]}
    metrics_recent = [{"hr_resting": 50.0, "sleep_asleep_minutes": 420.0} for _ in range(7)]
    metrics_baseline = [
        {"hr_resting": 50.0, "sleep_asleep_minutes": 420.0} for _ in range(28)
    ]

    dal = StubDal(plan_rows, lift_history, metrics_recent, metrics_baseline)

    captured: Dict[str, Any] = {}

    def fake_calibrate(rows, *, lift_history, recent_metrics, baseline_metrics):
        captured.update(
            {
                "rows": rows,
                "lift_history": lift_history,
                "recent_metrics": recent_metrics,
                "baseline_metrics": baseline_metrics,
            }
        )
        return PlanProgressionDecision(
            notes=["ok"],
            updates=[
                WorkoutProgression(
                    workout_id=2001,
                    exercise_id=501,
                    name="Back Squat",
                    before=100.0,
                    after=105.0,
                )
            ],
            persisted=False,
        )

    monkeypatch.setattr(
        "pete_e.application.progression_service.calibrate_plan_week",
        fake_calibrate,
    )

    service = ProgressionService(dal)
    decision = service.calibrate_plan_week(plan_id=10, week_number=1)

    assert captured["rows"] == plan_rows
    assert captured["lift_history"] == lift_history
    assert captured["recent_metrics"] == metrics_recent
    assert captured["baseline_metrics"] == metrics_baseline
    assert dal.loaded_ids == [[501]]
    assert dal.updated_targets and dal.updated_targets[0][0]["workout_id"] == 2001
    assert dal.refresh_calls == 1
    assert decision.persisted is True


def test_calibrate_plan_week_can_skip_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    dal = StubDal(
        _make_plan_rows(),
        lift_history={},
        recent_metrics=[],
        baseline_metrics=[],
    )

    monkeypatch.setattr(
        "pete_e.application.progression_service.calibrate_plan_week",
        lambda *args, **kwargs: PlanProgressionDecision(notes=[], updates=[], persisted=False),
    )

    service = ProgressionService(dal)
    decision = service.calibrate_plan_week(plan_id=5, week_number=2, persist=False)

    assert decision.persisted is False
    assert not dal.updated_targets
    assert dal.refresh_calls == 0
