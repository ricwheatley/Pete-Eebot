from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from pete_e.application import wger_sender


@pytest.fixture(autouse=True)
def stub_validation(monkeypatch):
    class StubValidationService:
        def __init__(self, dal):
            self.dal = dal

        def validate_and_adjust_plan(self, start_date):
            return SimpleNamespace(
                explanation="ok",
                log_entries=[],
                readiness=None,
                recommendation=SimpleNamespace(set_multiplier=1.0, rir_increment=0, metrics={}),
                should_apply=False,
                applied=False,
                needs_backoff=False,
            )

        def get_adherence_snapshot(self, start_date):
            return None

    monkeypatch.setattr(wger_sender, "ValidationService", StubValidationService)


class RecordingDal:
    def __init__(self, exported: bool = False) -> None:
        self._exported = exported

    def was_week_exported(self, plan_id: int, week_number: int) -> bool:
        return self._exported

    def get_plan_week_rows(self, plan_id: int, week_number: int):
        return [{"day_of_week": 1, "exercise_id": 100, "sets": 3, "reps": 5}]

    def record_wger_export(self, *_, **__):
        pass


def test_push_week_forwards_to_export_service(monkeypatch):
    calls = {"export": []}

    class StubExportService:
        def __init__(self, dal, client):
            pass

        def export_plan_week(self, *, plan_id: int, week_number: int, start_date: date, force_overwrite: bool):
            calls["export"].append((plan_id, week_number, start_date, force_overwrite))
            return {"status": "exported"}

    monkeypatch.setattr(wger_sender, "WgerClient", lambda: SimpleNamespace())
    monkeypatch.setattr(wger_sender, "WgerExportService", StubExportService)
    monkeypatch.setattr(
        wger_sender.log_utils,
        "log_message",
        lambda message, level="INFO": calls.setdefault("log", []).append((level, message)),
    )

    result = wger_sender.push_week(
        RecordingDal(exported=False),
        plan_id=10,
        week=2,
        start_date=date(2024, 6, 17),
    )

    assert result["status"] == "exported"
    assert calls["export"] == [(10, 2, date(2024, 6, 17), True)]


def test_push_week_logs_skip_when_exported(monkeypatch):
    logs = []

    class StubExportService:
        def __init__(self, dal, client):
            pass

        def export_plan_week(self, **kwargs):
            return {"status": "skipped"}

    monkeypatch.setattr(wger_sender, "WgerClient", lambda: SimpleNamespace())
    monkeypatch.setattr(wger_sender, "WgerExportService", StubExportService)
    monkeypatch.setattr(
        wger_sender.log_utils,
        "log_message",
        lambda message, level="INFO": logs.append((level, message)),
    )

    result = wger_sender.push_week(
        RecordingDal(exported=False),
        plan_id=5,
        week=1,
        start_date=date(2024, 7, 1),
    )

    assert result["status"] == "skipped"
    assert any("skipping push" in msg.lower() for _, msg in logs)
