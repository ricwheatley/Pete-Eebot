from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from pete_e.application.services import WgerExportService


class StubValidationService:
    def __init__(self):
        self.calls: list[date] = []

    def validate_and_adjust_plan(self, start_date: date):
        self.calls.append(start_date)
        return SimpleNamespace(explanation="ok", log_entries=[], readiness=None, recommendation=SimpleNamespace(set_multiplier=1.0, rir_increment=0, metrics={}), should_apply=False, applied=False, needs_backoff=False)

    def get_adherence_snapshot(self, start_date: date):
        return None


class StubDal:
    def __init__(self) -> None:
        self.was_week_exported_calls: List[tuple[int, int]] = []
        self.export_logs: List[Dict[str, Any]] = []
        self.rows: List[Dict[str, Any]] = [
            {"day_of_week": 1, "exercise_id": 100, "sets": 3, "reps": 5},
            {"day_of_week": 1, "exercise_id": 200, "sets": 2, "reps": 8},
        ]

    def was_week_exported(self, plan_id: int, week_number: int) -> bool:
        self.was_week_exported_calls.append((plan_id, week_number))
        return False

    def get_plan_week_rows(self, plan_id: int, week_number: int):
        return list(self.rows)

    def record_wger_export(self, plan_id: int, week_number: int, payload: Dict[str, Any], response: Dict[str, Any], routine_id: int | None = None):
        self.export_logs.append(
            {"plan_id": plan_id, "week_number": week_number, "payload": payload, "response": response, "routine_id": routine_id}
        )


class StubWgerClient:
    def __init__(self) -> None:
        self.calls: List[str] = []

    def find_or_create_routine(self, *, name: str, description: str, start: date, end: date):
        self.calls.append(f"routine:{name}")
        return {"id": 11}

    def delete_all_days_in_routine(self, routine_id: int) -> None:
        self.calls.append(f"delete:{routine_id}")


def test_export_service_builds_payload_and_records(monkeypatch: pytest.MonkeyPatch) -> None:
    dal = StubDal()
    client = StubWgerClient()
    validation_service = StubValidationService()
    service = WgerExportService(dal=dal, wger_client=client, validation_service=validation_service)

    result = service.export_plan_week(plan_id=5, week_number=1, start_date=date(2024, 6, 3), force_overwrite=True)

    assert result["status"] == "exported"
    assert dal.was_week_exported_calls == []  # force overwrite bypasses idempotency check
    assert client.calls == ["routine:Pete-E Week 2024-06-03", "delete:11"]
    assert dal.export_logs and dal.export_logs[0]["payload"]["days"][0]["exercises"][0]["sets"] == 3


def test_export_service_respects_existing_export(monkeypatch: pytest.MonkeyPatch) -> None:
    class AlreadyExportedDal(StubDal):
        def was_week_exported(self, plan_id: int, week_number: int) -> bool:
            return True

    dal = AlreadyExportedDal()
    client = StubWgerClient()
    validation_service = StubValidationService()
    service = WgerExportService(dal=dal, wger_client=client, validation_service=validation_service)

    result = service.export_plan_week(plan_id=9, week_number=1, start_date=date(2024, 6, 10))

    assert result["status"] == "skipped"
    assert not dal.export_logs
    assert client.calls == []

