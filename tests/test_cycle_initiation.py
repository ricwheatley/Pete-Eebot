from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from pete_e.cli import messenger


@pytest.fixture()
def cli_runner() -> CliRunner:
    return CliRunner()


def test_lets_begin_seeds_strength_test_week_when_macrocycle_missing(cli_runner, monkeypatch):
    calls: dict[str, object] = {}

    class StubPlanService:
        def create_and_persist_strength_test_week(self, start_date: date) -> int:
            calls["start_date"] = start_date
            return 101

    class StubDal:
        def __init__(self) -> None:
            self.marked: list[int] = []

        def mark_plan_active(self, plan_id: int) -> None:
            self.marked.append(plan_id)

    stub_dal = StubDal()
    stub_plan_service = StubPlanService()

    orchestrator = SimpleNamespace(
        plan_service=stub_plan_service,
        dal=stub_dal,
    )

    log_messages: list[str] = []
    monkeypatch.setattr(messenger, "_build_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(messenger, "push_week", lambda dal, plan_id, week, start_date: {"status": "exported"})
    monkeypatch.setattr(messenger.log_utils, "log_message", lambda message, level="INFO": log_messages.append(message))

    result = cli_runner.invoke(messenger.app, ["lets-begin", "--start-date", "2024-05-06"])

    assert result.exit_code == 0
    assert calls["start_date"] == date(2024, 5, 6)
    assert stub_dal.marked == [101]
    assert "Strength test week created via manual trigger." in result.stdout


def test_lets_begin_defaults_to_next_monday(cli_runner, monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2024, 5, 7)  # Tuesday

    created: dict[str, date] = {}

    class StubPlanService:
        def create_and_persist_strength_test_week(self, start_date: date) -> int:
            created["start_date"] = start_date
            return 1

    orchestrator = SimpleNamespace(plan_service=StubPlanService(), dal=SimpleNamespace(mark_plan_active=lambda pid: None))

    monkeypatch.setattr(messenger, "_build_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(messenger, "push_week", lambda dal, plan_id, week, start_date: {"status": "exported"})
    monkeypatch.setattr(messenger, "date", FixedDate)

    result = cli_runner.invoke(messenger.app, ["lets-begin"])

    assert result.exit_code == 0
    assert created["start_date"] == date(2024, 5, 13)
    assert "New macrocycle started successfully!" in result.stdout
