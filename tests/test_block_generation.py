from datetime import date
from typing import Any, Dict, List

import pytest

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator


class RecordingDal:
    def __init__(self) -> None:
        self.saved_plans: List[Dict[str, Any]] = []

    def save_training_plan(self, plan: Dict[str, Any], start_date: date) -> int:
        self.saved_plans.append({"plan": plan, "start_date": start_date})
        return len(self.saved_plans)


def test_generate_next_block_uses_training_maxes(monkeypatch: pytest.MonkeyPatch) -> None:
    start_date = date(2024, 1, 1)
    expected_tm = {
        "bench": 120.0,
        "squat": 180.0,
        "deadlift": 220.0,
        "ohp": 70.0,
    }

    dal = RecordingDal()

    def fake_build_block(
        dal_arg,
        start_date_arg,
        *,
        weeks: int = 4,
        training_maxes: Dict[str, float],
    ) -> int:
        assert dal_arg is dal
        assert start_date_arg == start_date
        assert weeks == 4
        assert training_maxes == expected_tm

        plan = {
            "weeks": [
                {
                    "week_number": index + 1,
                    "workouts": [
                        {
                            "exercise": "bench",
                            "target_weight_kg": training_maxes["bench"] * 0.9,
                        },
                        {
                            "exercise": "squat",
                            "target_weight_kg": training_maxes["squat"] * 0.85,
                        },
                    ],
                }
                for index in range(weeks)
            ]
        }
        return dal_arg.save_training_plan(plan, start_date_arg)

    monkeypatch.setattr(
        orchestrator_module,
        "build_block",
        fake_build_block,
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_module.plan_rw,
        "latest_training_max",
        lambda: expected_tm,
    )

    orch = Orchestrator(dal=dal)

    plan_id = orch.generate_next_block(start_date=start_date)

    assert plan_id == 1
    assert len(dal.saved_plans) == 1
    saved_plan = dal.saved_plans[0]["plan"]
    assert len(saved_plan["weeks"]) == 4
    first_week = saved_plan["weeks"][0]
    targets = [workout["target_weight_kg"] for workout in first_week["workouts"]]
    assert targets == [pytest.approx(expected_tm["bench"] * 0.9), pytest.approx(expected_tm["squat"] * 0.85)]


def test_progress_to_next_block_applies_531(monkeypatch: pytest.MonkeyPatch) -> None:
    start_date = date(2024, 2, 5)
    current_tm = {
        "bench": 100.0,
        "ohp": 60.0,
        "squat": 180.0,
        "deadlift": 220.0,
        "other": 50.0,
    }

    monkeypatch.setattr(
        orchestrator_module.plan_rw,
        "latest_training_max",
        lambda: current_tm,
    )

    calls: List[Dict[str, Any]] = []

    def fake_generate_next_block(
        self: Orchestrator,
        *,
        start_date: date | None = None,
        training_maxes: Dict[str, float] | None = None,
        weeks: int = 4,
    ) -> int:
        calls.append(
            {
                "start_date": start_date,
                "training_maxes": training_maxes,
                "weeks": weeks,
            }
        )
        return 42

    monkeypatch.setattr(
        Orchestrator,
        "generate_next_block",
        fake_generate_next_block,
        raising=False,
    )

    orch = Orchestrator(dal=RecordingDal())
    plan_id = orch.progress_to_next_block(start_date=start_date)

    assert plan_id == 42
    assert calls and calls[0]["start_date"] == start_date
    expected_tm = {
        "bench": current_tm["bench"] + 2.5,
        "ohp": current_tm["ohp"] + 2.5,
        "squat": current_tm["squat"] + 5.0,
        "deadlift": current_tm["deadlift"] + 5.0,
        "other": current_tm["other"],
    }
    assert calls[0]["weeks"] == 4
    for lift, value in expected_tm.items():
        assert calls[0]["training_maxes"][lift] == pytest.approx(value)

