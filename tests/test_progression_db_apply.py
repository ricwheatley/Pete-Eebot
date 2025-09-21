from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import pytest

from pete_e.config import settings
from pete_e.domain.progression import calibrate_plan_week


def _make_metrics(hr: float, sleep: float, days: int) -> List[Dict[str, Any]]:
    return [
        {"hr_resting": hr, "sleep_asleep_minutes": sleep}
        for _ in range(days)
    ]


class ProgressionDal:
    def __init__(
        self,
        plan_rows: List[Dict[str, Any]],
        lift_history: Dict[str, List[Dict[str, Any]]],
        recent_metrics: List[Dict[str, Any]],
        baseline_metrics: List[Dict[str, Any]],
    ) -> None:
        self._plan_rows = plan_rows
        self._lift_history = lift_history
        self._recent_metrics = recent_metrics
        self._baseline_metrics = baseline_metrics
        self.updated_targets: List[Dict[str, Any]] = []
        self.refresh_plan_view_called = 0

    def get_plan_week(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:  # noqa: ARG002
        return list(self._plan_rows)

    def load_lift_log(self, exercise_ids: List[int] | None = None, **_: Any) -> Dict[str, Any]:
        if not exercise_ids:
            return self._lift_history
        keys = {str(eid) for eid in exercise_ids}
        return {k: v for k, v in self._lift_history.items() if k in keys}

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        if days == 7:
            return self._recent_metrics
        if days == settings.BASELINE_DAYS:
            return self._baseline_metrics
        return []

    def update_workout_targets(self, updates: List[Dict[str, Any]]) -> None:
        self.updated_targets.extend(updates)

    def refresh_plan_view(self) -> None:
        self.refresh_plan_view_called += 1

    # The progression module probes for optional DAL helpers; unused methods exist for interface parity
    def __getattr__(self, name: str) -> Any:  # pragma: no cover - defensive fallback
        raise AttributeError(name)


@pytest.fixture
def plan_rows() -> List[Dict[str, Any]]:
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


@pytest.fixture
def metrics() -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    recent = _make_metrics(50.0, 420.0, 7)
    baseline = _make_metrics(50.0, 420.0, settings.BASELINE_DAYS)
    return recent, baseline


def _build_dal(
    plan_rows: List[Dict[str, Any]],
    lift_history: Dict[str, List[Dict[str, Any]]],
    metrics: tuple[List[Dict[str, Any]], List[Dict[str, Any]]],
) -> ProgressionDal:
    recent, baseline = metrics
    return ProgressionDal(plan_rows, lift_history, recent, baseline)


def test_calibrate_plan_week_updates_db_and_refreshes_view(plan_rows, metrics):
    lift_history = {
        "501": [
            {"weight": 100.0, "rir": 1.0},
            {"weight": 100.0, "rir": 1.0},
            {"weight": 100.0, "rir": 1.0},
            {"weight": 100.0, "rir": 0.5},
        ]
    }
    dal = _build_dal(plan_rows, lift_history, metrics)

    decision = calibrate_plan_week(dal, plan_id=99, week_number=1, persist=True)

    assert decision.persisted is True
    assert len(dal.updated_targets) == 1
    assert dal.updated_targets[0]["workout_id"] == 2001
    assert dal.updated_targets[0]["target_weight_kg"] == pytest.approx(107.5)
    assert dal.refresh_plan_view_called == 1
    assert decision.updates[0].before == pytest.approx(100.0)
    assert decision.updates[0].after == pytest.approx(107.5)


def test_calibrate_plan_week_notes_include_rir_and_recovery(plan_rows, metrics):
    lift_history = {
        "501": [
            {"weight": 100.0, "rir": 0.5},
            {"weight": 100.0, "rir": 0.5},
            {"weight": 100.0, "rir": 0.5},
            {"weight": 100.0, "rir": 0.5},
        ]
    }
    dal = _build_dal(plan_rows, lift_history, metrics)

    decision = calibrate_plan_week(dal, plan_id=99, week_number=1, persist=False)

    assert any("RIR" in note and "recovery" in note for note in decision.notes)


def test_calibrate_plan_week_logs_recovery_without_history(plan_rows, metrics):
    dal = _build_dal(plan_rows, lift_history={}, metrics=metrics)

    decision = calibrate_plan_week(dal, plan_id=99, week_number=1, persist=False)

    assert decision.persisted is False
    assert not decision.updates
    assert any("recovery" in note for note in decision.notes)
    assert any("no RIR" in note for note in decision.notes)
