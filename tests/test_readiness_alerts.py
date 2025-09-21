from datetime import date, timedelta
from typing import Any, Dict, List

import pytest

from pete_e.application import orchestrator as orchestrator_module
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


class ReadinessStubDal:
    def __init__(
        self,
        plan_start: date,
        plan_rows: List[Dict[str, Any]],
        lift_history: Dict[str, List[Dict[str, Any]]],
        metrics_recent: List[Dict[str, Any]],
        metrics_baseline: List[Dict[str, Any]],
        historical_rows: List[Dict[str, Any]],
        daily_summary: Dict[str, Any] | None = None,
    ) -> None:
        self._active_plan = {
            "id": 99,
            "start_date": plan_start,
            "weeks": 12,
        }
        self._plan_rows = plan_rows
        self._lift_history = lift_history
        self._metrics_recent = metrics_recent
        self._metrics_baseline = metrics_baseline
        self._historical_rows = historical_rows
        self._daily_summary = daily_summary or {}
        self.updated_targets: List[Dict[str, Any]] = []
        self.backoff_calls: List[Dict[str, Any]] = []
        self.validation_logs: List[List[str]] = []

    def get_active_plan(self) -> Dict[str, Any]:
        return self._active_plan

    def get_plan_week(self, plan_id: int, week_number: int) -> List[Dict[str, Any]]:
        assert plan_id == self._active_plan["id"]
        return list(self._plan_rows)

    def load_lift_log(self, exercise_ids: List[int] | None = None, **_: Any) -> Dict[str, Any]:
        if not exercise_ids:
            return self._lift_history
        keys = {str(eid) for eid in exercise_ids}
        return {k: v for k, v in self._lift_history.items() if k in keys}

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        if days == 7:
            return self._metrics_recent
        baseline_days = getattr(settings, "BASELINE_DAYS", 28)
        if days == baseline_days:
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

    def apply_plan_backoff(self, week_start_date: date, set_multiplier: float, rir_increment: int) -> None:
        self.backoff_calls.append(
            {
                "week_start": week_start_date,
                "set_multiplier": set_multiplier,
                "rir_increment": rir_increment,
            }
        )

    def save_validation_log(self, tag: str, adjustments: List[str]) -> None:
        self.validation_logs.append([tag, *adjustments])

    def get_daily_summary(self, target_date: date) -> Dict[str, Any] | None:
        if not self._daily_summary:
            return None
        result = dict(self._daily_summary)
        result.setdefault("date", target_date.isoformat())
        return result


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


def _build_stub(
    reference_date: date,
    plan_rows: List[Dict[str, Any]],
    lift_history: Dict[str, List[Dict[str, Any]]],
    *,
    recent_hr: float,
    recent_sleep: float,
    baseline_hr: float,
    baseline_sleep: float,
    historical_adjust: bool = False,
    daily_summary: Dict[str, Any] | None = None,
) -> ReadinessStubDal:
    metrics_recent = _make_metrics(recent_hr, recent_sleep, 7)
    baseline_days = getattr(settings, "BASELINE_DAYS", 28)
    metrics_baseline = _make_metrics(baseline_hr, baseline_sleep, baseline_days)

    history = _make_history(reference_date, 180, baseline_hr, baseline_sleep)
    if historical_adjust:
        history[:7] = _make_history(reference_date, 7, recent_hr, recent_sleep)

    plan_start = reference_date - timedelta(days=6)
    return ReadinessStubDal(
        plan_start=plan_start,
        plan_rows=plan_rows,
        lift_history=lift_history,
        metrics_recent=metrics_recent,
        metrics_baseline=metrics_baseline,
        historical_rows=history,
        daily_summary=daily_summary,
    )


def test_weekly_backoff_sends_single_readiness_alert(monkeypatch, plan_rows, lift_history):
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

    alerts: List[str] = []

    def fake_alert(message: str) -> bool:
        alerts.append(message)
        return True

    monkeypatch.setattr(
        orchestrator_module.telegram_sender,
        "send_alert",
        fake_alert,
        raising=False,
    )

    orch = Orchestrator(dal=dal)
    orch.run_weekly_calibration(reference_date=reference)

    assert len(alerts) == 1, alerts
    assert "readiness" in alerts[0].lower()


def test_daily_summary_includes_readiness_tip_when_flagged(monkeypatch, plan_rows, lift_history):
    reference = date(2025, 9, 7)
    target_day = reference - timedelta(days=1)
    summary_payload = {
        "steps": 4200,
        "hr_resting": 58.0,
        "sleep_asleep_minutes": 360,
        "readiness_state": "lagging",
        "readiness_tip": "Early night and extend warm-up",
    }
    dal = _build_stub(
        reference,
        plan_rows,
        lift_history,
        recent_hr=60.0,
        recent_sleep=360.0,
        baseline_hr=50.0,
        baseline_sleep=420.0,
        historical_adjust=True,
        daily_summary=summary_payload,
    )

    orch = Orchestrator(dal=dal)
    summary_text = orch.get_daily_summary(target_date=target_day)

    assert "readiness" in summary_text.lower()
    assert "early night" in summary_text.lower()
