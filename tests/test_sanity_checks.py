from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from pete_e.application.services import WgerExportService


class StubValidationService:
    def validate_and_adjust_plan(self, start_date: date):
        return SimpleNamespace(
            explanation="ok",
            log_entries=[],
            readiness=None,
            recommendation=SimpleNamespace(set_multiplier=1.0, rir_increment=0, metrics={}),
            should_apply=False,
            applied=False,
            needs_backoff=False,
        )

    def get_adherence_snapshot(self, start_date: date):
        return None


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
    validation_service = StubValidationService()
    service = WgerExportService(dal=dal, wger_client=None, validation_service=validation_service)  # client unused in dry-run path

    result = service.export_plan_week(
        plan_id=1,
        week_number=1,
        start_date=date(2024, 6, 1),
        dry_run=True,
    )

    assert result["status"] == "dry-run"
    assert result["payload"]["week_number"] == 1
