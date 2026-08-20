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
            """Initialize this object."""

        def assess_plan(self, start_date):
            return SimpleNamespace(
                explanation="ok",
                log_entries=[],
                readiness=None,
                recommendation=SimpleNamespace(set_multiplier=1.0, rir_increment=0, metrics={}),
                should_apply=False,
                applied=False,
                needs_backoff=False,
                source_data_hash="source-hash",
                plan_id=None,
                week_number=None,
            )
            """Perform assess plan."""

        def apply_adjustment(self, decision, **kwargs):
            decision.applied = True
            decision.plan_id = kwargs["plan_id"]
            decision.week_number = kwargs["week_number"]
            return decision
            """Perform apply adjustment."""

        def validate_and_adjust_plan(self, start_date):  # pragma: no cover
            raise AssertionError("sender must not use the composed validation path")

        def get_adherence_snapshot(self, start_date):
            return None
            """Perform get adherence snapshot."""
        """Represent StubValidationService."""

    monkeypatch.setattr(wger_sender, "ValidationService", StubValidationService)
    """Perform stub validation."""


class RecordingDal:
    def __init__(self, exported: bool = False) -> None:
        self._exported = exported
        """Initialize this object."""

    def was_week_exported(self, plan_id: int, week_number: int) -> bool:
        return self._exported
        """Perform was week exported."""

    def get_plan_week_rows(self, plan_id: int, week_number: int):
        return [{"day_of_week": 1, "exercise_id": 100, "sets": 3, "reps": 5}]
        """Perform get plan week rows."""

    def record_wger_export(self, *_, **__):
        pass
        """Perform record wger export."""
    """Represent RecordingDal."""


def test_push_week_forwards_to_export_service(monkeypatch):
    calls = {"export": []}

    class StubExportService:
        def __init__(self, dal, client):
            pass
            """Initialize this object."""

        def export_plan_week(
            self,
            *,
            plan_id: int,
            week_number: int,
            start_date: date,
            force_overwrite: bool,
            validation_decision=None,
        ):
            calls["export"].append((plan_id, week_number, start_date, force_overwrite, validation_decision))
            return {"status": "exported"}
            """Perform export plan week."""
        """Represent StubExportService."""

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
    assert len(calls["export"]) == 1
    exported = calls["export"][0]
    assert exported[:4] == (10, 2, date(2024, 6, 17), True)
    assert exported[4].applied is True
    assert exported[4].plan_id == 10
    assert exported[4].week_number == 2
    """Perform test push week forwards to export service."""


def test_push_week_logs_skip_when_exported(monkeypatch):
    logs = []

    class StubExportService:
        def __init__(self, dal, client):
            pass
            """Initialize this object."""

        def export_plan_week(self, **kwargs):
            return {"status": "skipped"}
            """Perform export plan week."""
        """Represent StubExportService."""

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
    """Perform test push week logs skip when exported."""


def test_push_week_applies_once_and_passes_decision_to_export(monkeypatch) -> None:
    events: list[str] = []
    decision = SimpleNamespace(
        explanation="back off",
        log_entries=[],
        readiness=None,
        recommendation=SimpleNamespace(set_multiplier=0.8, rir_increment=1, metrics={}),
        should_apply=True,
        applied=False,
        needs_backoff=True,
        source_data_hash="source-v1",
        plan_id=None,
        week_number=None,
    )

    class RecordingValidationService:
        def __init__(self, dal):
            pass

        def assess_plan(self, start_date):
            events.append("assess")
            return decision

        def apply_adjustment(self, assessed, **kwargs):
            events.append("apply")
            assessed.applied = True
            assessed.plan_id = kwargs["plan_id"]
            assessed.week_number = kwargs["week_number"]
            return assessed

        def get_adherence_snapshot(self, start_date):
            return None

    class RecordingExportService:
        def __init__(self, dal, client):
            pass

        def export_plan_week(self, **kwargs):
            events.append("export")
            assert kwargs["validation_decision"] is decision
            return {"status": "exported"}

    monkeypatch.setattr(wger_sender, "ValidationService", RecordingValidationService)
    monkeypatch.setattr(wger_sender, "WgerExportService", RecordingExportService)
    monkeypatch.setattr(wger_sender, "WgerClient", lambda: SimpleNamespace())
    monkeypatch.setattr(wger_sender.log_utils, "log_message", lambda *args, **kwargs: None)

    result = wger_sender.push_week(
        RecordingDal(),
        plan_id=22,
        week=3,
        start_date=date(2024, 6, 24),
    )

    assert result == {"status": "exported"}
    assert events == ["assess", "apply", "export"]
