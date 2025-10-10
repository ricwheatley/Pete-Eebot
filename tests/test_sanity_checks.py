from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import pytest

from pete_e.application.services import WgerExportService


@pytest.fixture(autouse=True)
def stub_validation(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "pete_e.application.services.validate_and_adjust_plan",
        lambda dal, start_date: SimpleNamespace(explanation="ok"),
    )


class DryRunDal:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = [
            {"day_of_week": 1, "exercise_id": 10, "sets": 3, "reps": 5},
        ]

    def was_week_exported(self, plan_id: int, week_number: int) -> bool:
        return False

    def get_plan_week_rows(self, plan_id: int, week_number: int):
        return list(self.rows)

    def record_wger_export(self, *_, **__):  # pragma: no cover - dry run path should skip persistence
        raise AssertionError("dry run should not persist")


def test_export_service_dry_run_returns_payload():
    dal = DryRunDal()
    service = WgerExportService(dal=dal, wger_client=None)  # client unused in dry-run path

    result = service.export_plan_week(
        plan_id=1,
        week_number=1,
        start_date=date(2024, 6, 1),
        dry_run=True,
    )

    assert result["status"] == "dry-run"
    assert result["payload"]["week_number"] == 1
