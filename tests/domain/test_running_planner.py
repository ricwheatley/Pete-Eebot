from pete_e.domain import schedule_rules
from pete_e.domain.running_planner import RunningPlanner


def test_running_planner_builds_consistent_weekly_sessions() -> None:
    planner = RunningPlanner()

    week1 = planner.build_week_sessions(week_number=1)
    week2 = planner.build_week_sessions(week_number=2)

    assert len(week1) == 5
    assert [session["day_of_week"] for session in week1] == [1, 2, 4, 5, 6]
    assert all(session["exercise_id"] == schedule_rules.RUN_CARDIO_EXERCISE_ID for session in week1)

    monday_week1 = next(session for session in week1 if session["day_of_week"] == 1)
    monday_week2 = next(session for session in week2 if session["day_of_week"] == 1)
    assert monday_week1["details"]["session_type"] == "intervals"
    assert monday_week2["details"]["session_type"] == "tempo"

    long_run_week1 = next(session for session in week1 if session["day_of_week"] == 6)
    long_run_week2 = next(session for session in week2 if session["day_of_week"] == 6)
    assert long_run_week1["details"]["steps"][0]["distance_km"] == 6
    assert long_run_week2["details"]["steps"][0]["distance_km"] == 7
