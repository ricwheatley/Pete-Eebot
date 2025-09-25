from __future__ import annotations

import os
from datetime import date
from types import SimpleNamespace

from typer.testing import CliRunner

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")

from pete_e.cli import messenger


runner = CliRunner()


def test_lets_begin_creates_strength_test_plan(monkeypatch):
    planned_start = date(2025, 9, 22)

    class FixedDate(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            return planned_start

    activations: list[int] = []
    build_calls: list[tuple[object, date]] = []
    push_calls: list[tuple[int, int, date]] = []

    monkeypatch.setattr(messenger, "date", FixedDate)

    def fake_build_strength(dal_arg, start_date):
        build_calls.append((dal_arg, start_date))
        return 42

    def fake_push_week(dal_arg, plan_id, week, start_date):
        push_calls.append((plan_id, week, start_date))
        return {"status": "exported"}

    dal = SimpleNamespace(mark_plan_active=lambda plan_id: activations.append(plan_id))
    orch = SimpleNamespace(dal=dal)

    monkeypatch.setattr(messenger, "build_strength_test", fake_build_strength)
    monkeypatch.setattr(messenger, "push_week", fake_push_week)
    monkeypatch.setattr(messenger, "_build_orchestrator", lambda: orch)

    result = runner.invoke(messenger.app, ["lets-begin"])

    assert result.exit_code == 0
    assert "Strength test week created via manual trigger." in result.stdout
    assert build_calls and build_calls[0][1] == planned_start
    assert activations == [42]
    assert push_calls == [(42, 1, planned_start)]
