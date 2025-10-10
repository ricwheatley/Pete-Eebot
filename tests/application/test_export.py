from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from pete_e.application.orchestrator import Orchestrator
from pete_e.application.services import WgerExportService
from pete_e.domain.validation import (
    BackoffRecommendation,
    ReadinessSummary,
    ValidationDecision,
)
from tests.di_utils import build_stub_container


def _make_validation_decision(explanation: str = "Ready") -> ValidationDecision:
    return ValidationDecision(
        needs_backoff=False,
        should_apply=False,
        explanation=explanation,
        log_entries=[],
        readiness=ReadinessSummary(
            state="ready",
            headline=explanation,
            tip=None,
            severity="low",
            breach_ratio=0.0,
            reasons=[],
        ),
        recommendation=BackoffRecommendation(
            needs_backoff=False,
            severity="none",
            reasons=[],
            set_multiplier=1.0,
            rir_increment=0,
            metrics={},
        ),
        applied=False,
    )


def test_export_plan_week_uses_cached_validation() -> None:
    decision = _make_validation_decision()
    validation_service = SimpleNamespace(
        validate_and_adjust_plan=MagicMock(name="validate"),
    )

    class StubDal:
        def was_week_exported(self, plan_id: int, week_number: int) -> bool:
            return False

        def get_plan_week_rows(self, plan_id: int, week_number: int):
            return []

        def record_wger_export(self, *_, **__):
            pass

    class StubClient:
        def find_or_create_routine(self, **kwargs):
            return {"id": 42}

        def delete_all_days_in_routine(self, routine_id: int) -> None:
            pass

    service = WgerExportService(
        dal=StubDal(),
        wger_client=StubClient(),
        validation_service=validation_service,
    )

    result = service.export_plan_week(
        plan_id=10,
        week_number=1,
        start_date=date(2024, 6, 3),
        force_overwrite=False,
        validation_decision=decision,
    )

    assert result["status"] == "exported"
    validation_service.validate_and_adjust_plan.assert_not_called()


def test_run_end_to_end_week_passes_cached_validation() -> None:
    decision = _make_validation_decision("All clear")

    class RecordingValidationService:
        def __init__(self, decision: ValidationDecision):
            self.decision = decision
            self.calls: list[date] = []

        def validate_and_adjust_plan(self, week_start: date) -> ValidationDecision:
            self.calls.append(week_start)
            return self.decision

    class StubPlanService:
        def __init__(self) -> None:
            self.created: list[date] = []

        def create_next_plan_for_cycle(self, *, start_date: date) -> int:
            self.created.append(start_date)
            return 99

    class RecordingExportService:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, date, ValidationDecision | None]] = []

        def export_plan_week(
            self,
            *,
            plan_id: int,
            week_number: int,
            start_date: date,
            force_overwrite: bool = False,
            validation_decision: ValidationDecision | None = None,
        ):
            self.calls.append((plan_id, week_number, start_date, validation_decision))
            return {"status": "exported"}

    class StubDal:
        def get_active_plan(self):
            return {"start_date": date(2024, 5, 6), "weeks": 4}

        def close(self) -> None:  # pragma: no cover - unused
            pass

    validation_service = RecordingValidationService(decision)
    plan_service = StubPlanService()
    export_service = RecordingExportService()

    container = build_stub_container(
        dal=StubDal(),
        wger_client=SimpleNamespace(),
        plan_service=plan_service,
        export_service=export_service,
    )

    cycle_service = SimpleNamespace(
        check_and_rollover=lambda active_plan, today: True,
    )

    orch = Orchestrator(
        container=container,
        validation_service=validation_service,
        cycle_service=cycle_service,
    )

    result = orch.run_end_to_end_week(reference_date=date(2024, 5, 26))

    assert result.rollover_triggered is True
    assert validation_service.calls == [date(2024, 5, 27)]
    assert export_service.calls == [(99, 1, date(2024, 5, 27), decision)]
