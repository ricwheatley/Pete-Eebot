from datetime import date, timedelta

from pete_e.domain import schedule_rules
from pete_e.domain.running_planner import (
    RunningGoal,
    RunningPlanner,
    assess_morning_run_adjustment,
)


def _recent_beginner_runs(as_of: date):
    distances = [3.2, 3.1, 3.0, 3.1, 3.1, 5.6, 4.2]
    return [
        {"workout_date": as_of - timedelta(days=idx * 3), "total_distance_km": distance}
        for idx, distance in enumerate(distances)
    ]


def test_running_planner_builds_foundation_block_from_low_run_base() -> None:
    planner = RunningPlanner()
    start = date(2026, 4, 27)
    runs = _recent_beginner_runs(start - timedelta(days=1))

    week1 = planner.build_week_sessions(
        week_number=1,
        plan_start_date=start,
        recent_runs=runs,
        goal=RunningGoal(target_race="marathon", race_date=date(2027, 4, 18), weight_loss_target_kg=22),
    )
    week2 = planner.build_week_sessions(
        week_number=2,
        plan_start_date=start,
        recent_runs=runs,
        goal=RunningGoal(target_race="marathon", race_date=date(2027, 4, 18), weight_loss_target_kg=22),
    )

    assert len(week1) == 3
    assert [session["day_of_week"] for session in week1] == [1, 4, 6]
    assert all(session["exercise_id"] == schedule_rules.RUN_CARDIO_EXERCISE_ID for session in week1)
    assert not any(session["comment"] == "Quality run" for session in week1)

    monday = next(session for session in week1 if session["day_of_week"] == 1)
    assert monday["details"]["session_type"] == "easy"
    assert monday["details"]["steps"][0]["speed_kph"] == 8.2

    long_run_week1 = next(session for session in week1 if session["day_of_week"] == 6)
    long_run_week2 = next(session for session in week2 if session["day_of_week"] == 6)
    assert long_run_week1["details"]["steps"][0]["distance_km"] == 6
    assert long_run_week2["details"]["steps"][0]["distance_km"] == 7


def test_running_planner_builds_recovery_week_when_health_metrics_are_poor() -> None:
    planner = RunningPlanner()
    start = date(2026, 4, 27)
    history = []
    for idx in range(60, 7, -1):
        history.append(
            {
                "date": start - timedelta(days=idx),
                "hr_resting": 50.0,
                "sleep_total_minutes": 420.0,
                "hrv_sdnn_ms": 60.0,
            }
        )
    for idx in range(7, 0, -1):
        history.append(
            {
                "date": start - timedelta(days=idx),
                "hr_resting": 66.0,
                "sleep_total_minutes": 300.0,
                "hrv_sdnn_ms": 40.0,
            }
        )

    week = planner.build_week_sessions(
        week_number=1,
        plan_start_date=start,
        health_metrics=history,
        recent_runs=_recent_beginner_runs(start - timedelta(days=1)),
    )

    assert len(week) == 1
    assert week[0]["comment"] == "Recovery run-walk"
    assert week[0]["optional"] is True
    assert week[0]["recovery_focused"] is True


def test_morning_run_adjustment_downgrades_planned_quality_when_recovery_dips() -> None:
    action_date = date(2026, 4, 27)
    history = []
    for idx in range(60, 7, -1):
        history.append(
            {
                "date": action_date - timedelta(days=idx),
                "hr_resting": 50.0,
                "sleep_total_minutes": 420.0,
                "hrv_sdnn_ms": 60.0,
            }
        )
    for idx in range(7, 0, -1):
        history.append(
            {
                "date": action_date - timedelta(days=idx),
                "hr_resting": 54.0,
                "sleep_total_minutes": 400.0,
                "hrv_sdnn_ms": 56.0,
            }
        )

    adjustment = assess_morning_run_adjustment(
        health_metrics=history,
        recent_runs=_recent_beginner_runs(action_date - timedelta(days=1)),
        action_date=action_date,
        planned_session_names=["Quality run", "Bench Press"],
    )

    assert adjustment is not None
    assert adjustment.should_backoff is True
    assert "Quality run" in adjustment.message
    assert "swap today's run" in adjustment.message
