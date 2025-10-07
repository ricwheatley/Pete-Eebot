"""Tests for starting a new macrocycle and associated CLI command."""

from __future__ import annotations

from datetime import date as real_date

import pytest
from typer.testing import CliRunner

import tests.rich_stub  # noqa: F401

from pete_e.application.orchestrator import Orchestrator
from pete_e.cli import messenger


class _StubOrchestrator:
    def __init__(self, recorder):
        self._recorder = recorder

    def start_new_macrocycle(self, start_date):
        self._recorder.append(start_date)


@pytest.fixture()
def cli_runner() -> CliRunner:
    return CliRunner()


def test_lets_begin_command_handles_explicit_and_default_start(cli_runner, monkeypatch):
    recorded: list[real_date] = []
    monkeypatch.setattr(messenger, "_build_orchestrator", lambda: _StubOrchestrator(recorded))

    result = cli_runner.invoke(messenger.app, ["lets-begin", "--start-date", "2024-05-06"])
    assert result.exit_code == 0
    assert recorded == [real_date(2024, 5, 6)]
    assert "Starting new 13-week 5/3/1 macrocycle" in result.stdout

    class FixedDate(real_date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2024, 5, 7)  # Tuesday

    recorded.clear()
    monkeypatch.setattr(messenger, "date", FixedDate)

    result = cli_runner.invoke(messenger.app, ["lets-begin"])
    assert result.exit_code == 0
    assert recorded == [real_date(2024, 5, 13)]  # Next Monday after 2024-05-07
    assert "New macrocycle started successfully!" in result.stdout


def test_orchestrator_start_new_macrocycle_invokes_dependencies(monkeypatch):
    captured: dict[str, object] = {}

    class StubDal:
        def __init__(self):
            self.deactivated = False
            self.created_args: tuple | None = None

        def deactivate_active_training_cycles(self) -> None:
            self.deactivated = True

        def create_training_cycle(self, start_date, *, current_week, current_block):
            self.created_args = (start_date, current_week, current_block)
            return {
                "id": 99,
                "start_date": start_date,
                "current_week": current_week,
                "current_block": current_block,
                "active": True,
            }

    dal = StubDal()
    orchestrator = Orchestrator(dal=dal)

    def fake_send(message: str) -> bool:
        captured["telegram_message"] = message
        return True

    def fake_generate(start_date):
        captured["generate_called_with"] = start_date
        return True

    monkeypatch.setattr(orchestrator, "send_telegram_message", fake_send, raising=False)
    monkeypatch.setattr(orchestrator, "generate_strength_test_week", fake_generate, raising=False)

    start = real_date(2024, 5, 6)
    result = orchestrator.start_new_macrocycle(start)

    assert dal.deactivated is True
    assert dal.created_args == (start, 1, 0)
    assert captured["generate_called_with"] == start
    assert "macrocycle" in captured["telegram_message"]
    assert result["id"] == 99
