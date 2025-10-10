from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

import pytest

import tests.config_stub  # noqa: F401

from pete_e.domain.validation import (
    PlanContext,
    collect_adherence_snapshot,
    validate_and_adjust_plan,
)


def _make_history(
    week_start: date,
    *,
    recent_hr: float = 50.0,
    recent_sleep: float = 480.0,
    baseline_hr: float = 50.0,
    baseline_sleep: float = 480.0,
) -> List[Dict[str, Any]]:
    obs_end = week_start - timedelta(days=1)
    base_start = obs_end - timedelta(days=179)
    recent_start = obs_end - timedelta(days=6)

    rows: List[Dict[str, Any]] = []
    current = base_start
    while current <= obs_end:
        if current >= recent_start:
            hr = recent_hr
            sleep = recent_sleep
        else:
            hr = baseline_hr
            sleep = baseline_sleep
        rows.append({
            "date": current,
            "hr_resting": hr,
            "sleep_total_minutes": sleep,
        })
        current += timedelta(days=1)
    return rows


def _build_snapshot(
    *,
    plan_context: PlanContext,
    week_start: date,
    planned_by_week: Dict[int, List[Dict[str, Any]]],
    actual_by_week: Dict[int, List[Dict[str, Any]]],
) -> Dict[str, Any] | None:
    days_since_start = (week_start - plan_context.start_date).days
    if days_since_start <= 0:
        return None
    prev_week_number = days_since_start // 7
    if prev_week_number <= 0:
        return None

    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = week_start - timedelta(days=1)
    planned_rows = planned_by_week.get(prev_week_number, [])
    actual_rows = actual_by_week.get(prev_week_number, [])

    return collect_adherence_snapshot(
        plan_context=plan_context,
        week_number=prev_week_number,
        week_start=prev_week_start,
        week_end=prev_week_end,
        planned_rows=planned_rows,
        actual_rows=actual_rows,
    )


@pytest.fixture
def plan_start() -> date:
    return date(2025, 9, 1)


def test_low_adherence_reduces_volume(plan_start: date) -> None:
    planned = {
        2: [
            {"muscle_id": 101, "target_volume_kg": 120.0},
            {"muscle_id": 102, "target_volume_kg": 140.0},
        ]
    }
    actual = {
        2: [
            {"muscle_id": 101, "actual_volume_kg": 60.0},
            {"muscle_id": 102, "actual_volume_kg": 80.0},
        ]
    }
    week_start = plan_start + timedelta(days=14)

    history = _make_history(week_start)
    plan_context = PlanContext(plan_id=101, start_date=plan_start)
    snapshot = _build_snapshot(
        plan_context=plan_context,
        week_start=week_start,
        planned_by_week=planned,
        actual_by_week=actual,
    )

    decision = validate_and_adjust_plan(
        history,
        week_start,
        plan_context=plan_context,
        adherence_snapshot=snapshot,
    )

    assert decision.recommendation.set_multiplier == pytest.approx(0.90, rel=1e-3)
    assert decision.should_apply is True
    adherence_metrics = decision.recommendation.metrics.get("adherence")
    assert adherence_metrics and adherence_metrics.get("applied_direction") == "reduce"


def test_high_adherence_increases_volume_when_recovery_good(plan_start: date) -> None:
    planned = {
        2: [
            {"muscle_id": 201, "target_volume_kg": 100.0},
            {"muscle_id": 202, "target_volume_kg": 80.0},
        ]
    }
    actual = {
        2: [
            {"muscle_id": 201, "actual_volume_kg": 130.0},
            {"muscle_id": 202, "actual_volume_kg": 95.0},
        ]
    }
    week_start = plan_start + timedelta(days=14)

    history = _make_history(week_start)
    plan_context = PlanContext(plan_id=202, start_date=plan_start)
    snapshot = _build_snapshot(
        plan_context=plan_context,
        week_start=week_start,
        planned_by_week=planned,
        actual_by_week=actual,
    )

    decision = validate_and_adjust_plan(
        history,
        week_start,
        plan_context=plan_context,
        adherence_snapshot=snapshot,
    )

    assert decision.recommendation.set_multiplier == pytest.approx(1.05, rel=1e-3)
    assert decision.should_apply is True
    adherence_metrics = decision.recommendation.metrics.get("adherence")
    assert adherence_metrics and adherence_metrics.get("applied_direction") == "increase"


def test_high_adherence_blocked_when_recovery_flagged(plan_start: date) -> None:
    planned = {
        2: [
            {"muscle_id": 301, "target_volume_kg": 110.0},
            {"muscle_id": 302, "target_volume_kg": 90.0},
        ]
    }
    actual = {
        2: [
            {"muscle_id": 301, "actual_volume_kg": 130.0},
            {"muscle_id": 302, "actual_volume_kg": 110.0},
        ]
    }
    week_start = plan_start + timedelta(days=14)

    history = _make_history(
        week_start,
        recent_hr=55.0,
        baseline_hr=50.0,
    )
    plan_context = PlanContext(plan_id=303, start_date=plan_start)
    snapshot = _build_snapshot(
        plan_context=plan_context,
        week_start=week_start,
        planned_by_week=planned,
        actual_by_week=actual,
    )

    decision = validate_and_adjust_plan(
        history,
        week_start,
        plan_context=plan_context,
        adherence_snapshot=snapshot,
    )

    assert decision.recommendation.set_multiplier == pytest.approx(0.90, rel=1e-3)
    adherence_metrics = decision.recommendation.metrics.get("adherence")
    assert adherence_metrics and adherence_metrics.get("gated_by_recovery") is True
    assert adherence_metrics.get("applied_direction") != "increase"
