from __future__ import annotations

from datetime import date

import pytest
from typer.testing import CliRunner

from pete_e.cli import messenger


@pytest.fixture()
def cli_runner() -> CliRunner:
    return CliRunner()


def test_lets_begin_seeds_strength_test_week_when_macrocycle_missing(cli_runner, monkeypatch):
    log_messages: list[tuple[str, str]] = []

    class StubPlanGenerationService:
        def __init__(self) -> None:
            self.runs: list[date] = []

        def run(self, *, start_date: date) -> None:
            self.runs.append(start_date)

    class StubOrchestrator:
        instances: list["StubOrchestrator"] = []

        def __init__(self) -> None:
            self.plan_generation_service = StubPlanGenerationService()
            self.closed = False
            StubOrchestrator.instances.append(self)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("pete_e.application.orchestrator.Orchestrator", StubOrchestrator)
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level="INFO": log_messages.append((level, message)),
    )

    result = cli_runner.invoke(messenger.app, ["lets-begin", "--start-date", "2024-05-06"])

    assert result.exit_code == 0
    assert StubOrchestrator.instances, "Orchestrator should be constructed"
    orchestrator = StubOrchestrator.instances[0]
    assert orchestrator.plan_generation_service.runs == [date(2024, 5, 6)]
    assert orchestrator.closed is True

    assert "Starting new 13-week 5/3/1 macrocycle on 2024-05-06" in result.stdout
    assert "Strength test week created and exported successfully!" in result.stdout
    assert "New macrocycle initialized successfully" in result.stdout
    assert any(
        level == "PLAN"
        and message == "Strength test week created successfully via lets-begin at 2024-05-06"
        for level, message in log_messages
    )


def test_lets_begin_defaults_to_next_monday(cli_runner, monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2024, 5, 7)  # Tuesday

    log_messages: list[tuple[str, str]] = []

    class StubPlanGenerationService:
        def __init__(self) -> None:
            self.runs: list[date] = []

        def run(self, *, start_date: date) -> None:
            self.runs.append(start_date)

    class StubOrchestrator:
        instances: list["StubOrchestrator"] = []

        def __init__(self) -> None:
            self.plan_generation_service = StubPlanGenerationService()
            self.closed = False
            StubOrchestrator.instances.append(self)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("pete_e.application.orchestrator.Orchestrator", StubOrchestrator)
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level="INFO": log_messages.append((level, message)),
    )
    monkeypatch.setattr(messenger, "date", FixedDate)

    result = cli_runner.invoke(messenger.app, ["lets-begin"])

    assert result.exit_code == 0
    assert StubOrchestrator.instances, "Orchestrator should be constructed"
    orchestrator = StubOrchestrator.instances[0]
    assert orchestrator.plan_generation_service.runs == [date(2024, 5, 13)]
    assert orchestrator.closed is True

    assert "Starting new 13-week 5/3/1 macrocycle on 2024-05-13" in result.stdout
    assert "Strength test week created and exported successfully!" in result.stdout
    assert "New macrocycle initialized successfully" in result.stdout
    assert any(
        level == "PLAN"
        and message == "Strength test week created successfully via lets-begin at 2024-05-13"
        for level, message in log_messages
    )
