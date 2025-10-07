from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator
from pete_e.domain.schedule_rules import BENCH_ID, DEADLIFT_ID, OHP_ID, SQUAT_ID


def test_generate_strength_test_week_creates_and_exports(monkeypatch: pytest.MonkeyPatch) -> None:
    start_monday = date(2024, 1, 1)

    created: Dict[str, Any] = {}
    inserted_workouts: List[Dict[str, Any]] = []
    exported: Dict[str, Any] = {}
    marked_active: List[int] = []

    def fake_create_test_week_plan(start_date: date) -> tuple[int, int]:
        created["start_date"] = start_date
        return 123, 456

    def fake_latest_training_max() -> Dict[str, float]:
        return {
            "bench": 140.0,
            "squat": 200.0,
            "deadlift": 250.0,
            "ohp": 90.0,
        }

    def fake_insert_workout(**kwargs: Any) -> None:
        inserted_workouts.append(kwargs)

    def fake_build_week_payload(plan_id: int, week_number: int) -> Dict[str, Any]:
        return {"plan_id": plan_id, "week": week_number}

    def fake_export_week(payload: Dict[str, Any], **kwargs: Any) -> None:
        exported["payload"] = payload
        exported["kwargs"] = kwargs

    monkeypatch.setattr(orchestrator_module.plan_rw, "create_test_week_plan", fake_create_test_week_plan)
    monkeypatch.setattr(orchestrator_module.plan_rw, "latest_training_max", fake_latest_training_max)
    monkeypatch.setattr(orchestrator_module.plan_rw, "insert_workout", fake_insert_workout)
    monkeypatch.setattr(orchestrator_module.plan_rw, "build_week_payload", fake_build_week_payload)
    monkeypatch.setattr(orchestrator_module, "export_week_to_wger", fake_export_week)

    dal = SimpleNamespace(mark_plan_active=lambda plan_id: marked_active.append(plan_id))

    orch = Orchestrator(dal=dal)

    result = orch.generate_strength_test_week(start_date=start_monday)

    assert result == (123, 456)
    assert created == {"start_date": start_monday}
    assert len(inserted_workouts) == 9  # 5 Blaze sessions + 4 main lifts
    assert exported["payload"] == {"plan_id": 123, "week": 1}
    assert exported["kwargs"]["week_start"] == start_monday
    assert exported["kwargs"]["week_end"] == start_monday + timedelta(days=6)
    assert marked_active == [123]


def test_evaluate_strength_test_week_updates_training_maxes(monkeypatch: pytest.MonkeyPatch) -> None:
    start_monday = date(2024, 2, 5)
    week_end = start_monday + timedelta(days=6)

    monkeypatch.setattr(
        orchestrator_module.plan_rw,
        "latest_test_week",
        lambda: {"plan_id": 77, "week_number": 1, "start_date": start_monday},
    )
    monkeypatch.setattr(
        orchestrator_module.plan_rw,
        "week_date_range",
        lambda start, week: (start, start + timedelta(days=6)),
    )

    inserted: List[Dict[str, Any]] = []
    upserts: List[Dict[str, Any]] = []
    sent_messages: List[str] = []

    def fake_insert_strength_test_result(**kwargs: Any) -> None:
        inserted.append(kwargs)

    def fake_upsert_training_max(**kwargs: Any) -> None:
        upserts.append(kwargs)

    monkeypatch.setattr(
        orchestrator_module.plan_rw,
        "insert_strength_test_result",
        fake_insert_strength_test_result,
    )
    monkeypatch.setattr(
        orchestrator_module.plan_rw,
        "upsert_training_max",
        fake_upsert_training_max,
    )
    monkeypatch.setattr(
        Orchestrator,
        "send_telegram_message",
        lambda self, message: sent_messages.append(message) or True,
        raising=False,
    )

    def load_lift_log(*, exercise_ids, start_date, end_date):
        assert set(exercise_ids) == {BENCH_ID, SQUAT_ID, OHP_ID, DEADLIFT_ID}
        assert start_date == start_monday
        assert end_date == week_end
        return {
            str(BENCH_ID): [
                {"date": start_monday, "reps": 8, "weight_kg": 110.0},
            ],
            str(SQUAT_ID): [
                {"date": start_monday + timedelta(days=1), "reps": 6, "weight_kg": 180.0},
            ],
        }

    dal = SimpleNamespace(load_lift_log=load_lift_log)
    orch = Orchestrator(dal=dal)

    summary = orch.evaluate_strength_test_week()

    assert summary == {
        "status": "ok",
        "plan_id": "77",
        "week": "1",
        "start": str(start_monday),
        "end": str(week_end),
        "lifts_updated": "2",
    }

    assert len(inserted) == 2
    bench_result = next(item for item in inserted if item["lift_code"] == "bench")
    squat_result = next(item for item in inserted if item["lift_code"] == "squat")

    assert bench_result["tm_kg"] == pytest.approx(125.0)
    assert squat_result["tm_kg"] == pytest.approx(195.0)

    assert upserts == [
        {
            "lift_code": "bench",
            "tm_kg": pytest.approx(125.0),
            "measured_at": week_end,
            "source": "AMRAP_EPLEY",
        },
        {
            "lift_code": "squat",
            "tm_kg": pytest.approx(195.0),
            "measured_at": week_end,
            "source": "AMRAP_EPLEY",
        },
    ]

    assert len(sent_messages) == 1
    assert "Bench: TM 125.0 kg" in sent_messages[0]
    assert "Squat: TM 195.0 kg" in sent_messages[0]
