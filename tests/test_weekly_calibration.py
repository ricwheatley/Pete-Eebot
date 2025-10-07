from datetime import date, timedelta
from typing import Any, Dict, List

import pytest

from pete_e.application.orchestrator import Orchestrator
from pete_e.config import settings


def _make_metrics(hr: float, sleep: float, days: int) -> List[Dict[str, Any]]:
    return [
        {"hr_resting": hr, "sleep_asleep_minutes": sleep}
        for _ in range(days)
    ]


def _make_history(end: date, days: int, hr: float, sleep_total: float) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for offset in range(days):
        rows.append(
            {
                "date": end - timedelta(days=offset),
                "hr_resting": hr,
                "sleep_total_minutes": sleep_total,
            }
        )
    return rows


class StubDal:
    def __init__(
        self,
        plan_start: date,
        plan_rows: List[Dict[str, Any]],
        lift_history: Dict[str, List[Dict[str, Any]]],
        metrics_recent: List[Dict[str, Any]],
        metrics_baseline: List[Dict[str, Any]],
        historical_rows: List[Dict[str, Any]],
    ) -> None:
        self._active_plan = {
            "id": 42,
            "start_date": plan_start,
            "weeks": 8,
        }
        self._plan_rows = [dict(row) for row in plan_rows]
        self._lift_history = {
            key: [dict(entry) for entry in entries]
            for key, entries in lift_history.items()
        }
        self._metrics_recent = metrics_recent
        self._metrics_baseline = metrics_baseline
        self._historical_rows = historical_rows
        self.updated_targets: List[Dict[str, Any]] = []
        self.backoff_calls: List[Dict[str, Any]] = []
        self.validation_logs: List[List[str]] = []
        self._fail_backoff = False

    def get_active_plan(self) -> Dict[str, Any]:
        return self._active_plan

    def get_plan_week(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        assert plan_id == self._active_plan["id"]
        # Tests provide rows for the requested week only
        return list(self._plan_rows)

    def load_lift_log(self, exercise_ids: List[int] | None = None, **_: Any) -> Dict[str, Any]:
        if not exercise_ids:
            return self._lift_history
        keys = {str(eid) for eid in exercise_ids}
        return {k: v for k, v in self._lift_history.items() if k in keys}

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        if days == 7:
            return self._metrics_recent
        if days == getattr(settings, "BASELINE_DAYS", 28):
            return self._metrics_baseline
        return []

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        return [
            row
            for row in self._historical_rows
            if start_date <= row["date"] <= end_date
        ]

    def update_workout_targets(self, updates: List[Dict[str, Any]]) -> None:
        self.updated_targets.extend(updates)
        for update in updates:
            workout_id = update.get("workout_id")
            for row in self._plan_rows:
                if row.get("id") == workout_id:
                    row["target_weight_kg"] = update.get("target_weight_kg")

    def apply_plan_backoff(self, week_start_date: date, set_multiplier: float, rir_increment: int) -> None:
        if self._fail_backoff:
            raise RuntimeError("backoff failed")
        self.backoff_calls.append(
            {
                "week_start": week_start_date,
                "set_multiplier": set_multiplier,
                "rir_increment": rir_increment,
            }
        )

    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        self.validation_logs.append([tag, *adjustments])


@pytest.fixture
def plan_rows() -> List[Dict[str, Any]]:
    return [
        {
            "id": 1001,
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
def lift_history() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "501": [
            {"weight": 100.0, "rir": 1.0},
            {"weight": 100.0, "rir": 1.0},
            {"weight": 100.0, "rir": 1.0},
            {"weight": 100.0, "rir": 1.0},
        ]
    }


def _build_stub(reference_date: date, plan_rows: List[Dict[str, Any]], lift_history: Dict[str, List[Dict[str, Any]]], *, recent_hr: float, recent_sleep: float, baseline_hr: float, baseline_sleep: float, historical_adjust: bool = False) -> StubDal:
    metrics_recent = _make_metrics(recent_hr, recent_sleep, 7)
    baseline_days = getattr(settings, "BASELINE_DAYS", 28)
    metrics_baseline = _make_metrics(baseline_hr, baseline_sleep, baseline_days)

    history = _make_history(reference_date, 180, baseline_hr, baseline_sleep)
    if historical_adjust:
        # Override the most recent 7 days with the recent metrics
        history[:7] = _make_history(reference_date, 7, recent_hr, recent_sleep)

    plan_start = reference_date - timedelta(days=6)  # prior Monday
    return StubDal(
        plan_start=plan_start,
        plan_rows=plan_rows,
        lift_history=lift_history,
        metrics_recent=metrics_recent,
        metrics_baseline=metrics_baseline,
        historical_rows=history,
    )


def test_weekly_calibration_updates_load_without_backoff(plan_rows, lift_history):
    reference = date(2025, 9, 7)  # Sunday
    dal = _build_stub(
        reference,
        plan_rows,
        lift_history,
        recent_hr=50.0,
        recent_sleep=420.0,
        baseline_hr=50.0,
        baseline_sleep=420.0,
        historical_adjust=False,
    )

    orch = Orchestrator(dal=dal)
    result = orch.run_weekly_calibration(reference_date=reference)

    assert result.plan_id == 42
    assert result.week_number == 2
    assert dal.updated_targets, "progression should persist target adjustments"
    assert dal.updated_targets[0]["target_weight_kg"] is not None
    assert result.progression.persisted is True
    assert result.validation.needs_backoff is False
    assert not dal.backoff_calls
    assert dal.validation_logs  # log captured for audit
    assert f"Week {result.week_number}" in result.message


def test_weekly_calibration_applies_backoff_when_recovery_poor(plan_rows, lift_history):
    reference = date(2025, 9, 7)
    dal = _build_stub(
        reference,
        plan_rows,
        lift_history,
        recent_hr=60.0,
        recent_sleep=360.0,
        baseline_hr=50.0,
        baseline_sleep=420.0,
        historical_adjust=True,
    )

    orch = Orchestrator(dal=dal)
    result = orch.run_weekly_calibration(reference_date=reference)

    assert result.validation.needs_backoff is True
    assert result.validation.applied is True
    assert dal.backoff_calls, "back-off should be applied when recovery is poor"
    call = dal.backoff_calls[0]
    assert call["week_start"] == result.week_start
    assert "severity" in " ".join(result.validation.log_entries)
    assert "recalibrated" in result.message
    assert dal.validation_logs


def test_weekly_calibration_is_idempotent_when_no_progression_required(plan_rows):
    reference = date(2025, 9, 7)
    dal = _build_stub(
        reference,
        plan_rows,
        lift_history={},
        recent_hr=50.0,
        recent_sleep=420.0,
        baseline_hr=50.0,
        baseline_sleep=420.0,
        historical_adjust=False,
    )

    orch = Orchestrator(dal=dal)
    result = orch.run_weekly_calibration(reference_date=reference)

    assert result.progression.updates == []
    assert result.progression.persisted is False
    assert dal.updated_targets == []
    assert "No load adjustments required" in result.message
    assert result.validation.needs_backoff is False
    assert not dal.backoff_calls


def test_weekly_calibration_recommends_backoff_when_dal_cannot_apply(plan_rows, lift_history):
    reference = date(2025, 9, 7)
    dal = _build_stub(
        reference,
        plan_rows,
        lift_history,
        recent_hr=60.0,
        recent_sleep=360.0,
        baseline_hr=50.0,
        baseline_sleep=420.0,
        historical_adjust=True,
    )
    dal._fail_backoff = True

    orch = Orchestrator(dal=dal)
    result = orch.run_weekly_calibration(reference_date=reference)

    assert result.validation.needs_backoff is True
    assert result.validation.applied is False
    assert any(entry.startswith("apply_failed:") for entry in result.validation.log_entries)
    assert not dal.backoff_calls
    assert "back-off" in result.validation.explanation.lower()
    assert dal.validation_logs
