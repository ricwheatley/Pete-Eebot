from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pete_e.application.orchestrator import Orchestrator
from pete_e.application.services import WgerExportService
from pete_e.domain import schedule_rules
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
    """Perform make validation decision."""


def test_export_plan_week_uses_cached_validation() -> None:
    decision = _make_validation_decision()
    validation_service = SimpleNamespace(
        validate_and_adjust_plan=MagicMock(name="validate"),
    )

    class StubDal:
        def was_week_exported(self, plan_id: int, week_number: int) -> bool:
            return False
            """Perform was week exported."""

        def get_plan_week_rows(self, plan_id: int, week_number: int):
            return []
            """Perform get plan week rows."""

        def record_wger_export(self, *_, **__):
            pass
            """Perform record wger export."""
        """Represent StubDal."""

    class StubClient:
        def find_or_create_routine(self, **kwargs):
            return {"id": 42}
            """Perform find or create routine."""

        def delete_all_days_in_routine(self, routine_id: int) -> None:
            pass
            """Perform delete all days in routine."""
        """Represent StubClient."""

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
    """Perform test export plan week uses cached validation."""


def test_export_plan_week_uses_fallback_routine_when_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    recorded: list[dict[str, object]] = []

    class StubDal:
        def was_week_exported(self, plan_id: int, week_number: int) -> bool:
            return False
            """Perform was week exported."""

        def get_plan_week_rows(self, plan_id: int, week_number: int):
            return []
            """Perform get plan week rows."""

        def record_wger_export(self, plan_id, week_number, payload_json, response=None, routine_id=None):
            recorded.append({"response": response, "routine_id": routine_id})
            """Perform record wger export."""
        """Represent StubDal."""

    class StubClient:
        base_url = "https://example.invalid"

        def __init__(self) -> None:
            self.routine_names: list[str] = []
            """Initialize this object."""

        def find_or_create_routine(self, **kwargs):
            self.routine_names.append(kwargs["name"])
            return {"id": 1000 + len(self.routine_names)}
            """Perform find or create routine."""

        def delete_all_days_in_routine(self, routine_id: int) -> None:
            raise RuntimeError("DELETE /day/333279/ failed with 500")
            """Perform delete all days in routine."""
        """Represent StubClient."""

    monkeypatch.setattr("pete_e.application.services.log_utils.warn", warnings.append)
    monkeypatch.setattr(
        "pete_e.application.services.WgerExportService._fallback_routine_name",
        staticmethod(lambda base_name: f"{base_name} retry test"),
    )

    client = StubClient()
    service = WgerExportService(
        dal=StubDal(),
        wger_client=client,
        validation_service=SimpleNamespace(
            validate_and_adjust_plan=lambda start_date: _make_validation_decision()
        ),
    )

    result = service.export_plan_week(
        plan_id=10,
        week_number=1,
        start_date=date(2026, 4, 27),
        force_overwrite=True,
    )

    assert result == {"status": "exported", "routine_id": 1002}
    assert client.routine_names == [
        "Pete-E Week 2026-04-27",
        "Pete-E Week 2026-04-27 retry test",
    ]
    assert recorded and recorded[0]["routine_id"] == 1002
    assert any("Creating fallback routine" in warning for warning in warnings)
    """Perform test export plan week uses fallback routine when cleanup fails."""


def test_export_plan_week_labels_test_week_main_lifts_as_amrap() -> None:
    captured_payloads: list[dict] = []

    class StubDal:
        def was_week_exported(self, plan_id: int, week_number: int) -> bool:
            return False
            """Perform was week exported."""

        def get_plan_week_rows(self, plan_id: int, week_number: int):
            return [
                {
                    "id": 1,
                    "week_number": 1,
                    "is_test": True,
                    "day_of_week": 1,
                    "exercise_id": schedule_rules.BENCH_ID,
                    "sets": 1,
                    "reps": 1,
                    "percent_1rm": 85.0,
                    "target_weight_kg": 92.5,
                    "scheduled_time": "07:05:00",
                    "is_cardio": False,
                }
            ]
            """Perform get plan week rows."""

        def record_wger_export(self, plan_id, week_number, payload_json, response=None, routine_id=None):
            captured_payloads.append(payload_json)
            """Perform record wger export."""
        """Represent StubDal."""

    class StubClient:
        def find_or_create_routine(self, **kwargs):
            return {"id": 42}
            """Perform find or create routine."""

        def delete_all_days_in_routine(self, routine_id: int) -> None:
            pass
            """Perform delete all days in routine."""
        """Represent StubClient."""

    service = WgerExportService(
        dal=StubDal(),
        wger_client=StubClient(),
        validation_service=SimpleNamespace(
            validate_and_adjust_plan=lambda start_date: _make_validation_decision()
        ),
    )

    result = service.export_plan_week(
        plan_id=10,
        week_number=1,
        start_date=date(2024, 8, 5),
        force_overwrite=False,
    )

    assert result["status"] == "exported"
    assert captured_payloads
    entry = captured_payloads[0]["days"][0]["exercises"][0]
    assert entry["comment"] == "AMRAP Test @ 85.0% TM | 92.5 kg | Rest 2m 30s"
    """Perform test export plan week labels test week main lifts as amrap."""


def test_export_plan_week_posts_weight_config_for_target_loads() -> None:
    class StubDal:
        def was_week_exported(self, plan_id: int, week_number: int) -> bool:
            return False
            """Perform was week exported."""

        def get_plan_week_rows(self, plan_id: int, week_number: int):
            return [
                {
                    "id": 1,
                    "week_number": 2,
                    "is_test": False,
                    "day_of_week": 1,
                    "exercise_id": schedule_rules.BENCH_ID,
                    "sets": 5,
                    "reps": 3,
                    "rir": 2.0,
                    "percent_1rm": 90.0,
                    "target_weight_kg": 47.5,
                    "scheduled_time": "07:05:00",
                    "is_cardio": False,
                },
                {
                    "id": 2,
                    "week_number": 2,
                    "is_test": False,
                    "day_of_week": 2,
                    "exercise_id": schedule_rules.OHP_ID,
                    "sets": 5,
                    "reps": 5,
                    "rir": 2.0,
                    "percent_1rm": 65.0,
                    "target_weight_kg": 15.0,
                    "scheduled_time": "06:00:00",
                    "is_cardio": False,
                },
            ]
            """Perform get plan week rows."""

        def record_wger_export(self, *_, **__):
            pass
            """Perform record wger export."""
        """Represent StubDal."""

    class StubClient:
        def __init__(self) -> None:
            self.set_config_calls: list[tuple[str, int, int, object]] = []
            self.slot_entry_kwargs: list[dict[str, object]] = []
            """Initialize this object."""

        def find_or_create_routine(self, **kwargs):
            return {"id": 42}
            """Perform find or create routine."""

        def delete_all_days_in_routine(self, routine_id: int) -> None:
            pass
            """Perform delete all days in routine."""

        def create_day(self, routine_id: int, order: int, name: str):
            return {"id": 100 + order, "name": name}
            """Perform create day."""

        def create_slot(self, day_id: int, order: int, comment=None):
            return {"id": day_id * 10 + order}
            """Perform create slot."""

        def create_slot_entry(
            self,
            slot_id: int,
            exercise_id: int,
            order: int = 1,
            **kwargs,
        ):
            self.slot_entry_kwargs.append(kwargs)
            return {"id": slot_id * 10 + order}
            """Perform create slot entry."""

        def set_config(self, config_type: str, slot_entry_id: int, iteration: int, value):
            self.set_config_calls.append((config_type, slot_entry_id, iteration, value))
            """Perform set config."""
        """Represent StubClient."""

    client = StubClient()
    service = WgerExportService(
        dal=StubDal(),
        wger_client=client,
        validation_service=SimpleNamespace(
            validate_and_adjust_plan=lambda start_date: _make_validation_decision()
        ),
    )

    result = service.export_plan_week(
        plan_id=10,
        week_number=2,
        start_date=date(2024, 8, 12),
        force_overwrite=False,
    )

    assert result["status"] == "exported"
    weight_calls = [call for call in client.set_config_calls if call[0] == "weight"]
    assert weight_calls == [
        ("weight", 10111, 1, 47.5),
        ("weight", 10211, 1, 15.0),
    ]
    rest_calls = [call for call in client.set_config_calls if call[0] == "rest"]
    assert rest_calls == [
        ("rest", 10111, 1, 165),
        ("rest", 10211, 1, 165),
    ]
    assert client.slot_entry_kwargs[0]["comment"].startswith("Set 1 @ 90% TM")
    """Perform test export plan week posts weight config for target loads."""


def test_export_plan_week_orders_sessions_and_creates_visible_limber_11(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []
    infos: list[str] = []

    class StubDal:
        def was_week_exported(self, plan_id: int, week_number: int) -> bool:
            return False
            """Perform was week exported."""

        def get_plan_week_rows(self, plan_id: int, week_number: int):
            return [
                {
                    "id": 1,
                    "week_number": 1,
                    "day_of_week": 1,
                    "exercise_id": 137,
                    "sets": 3,
                    "reps": 10,
                    "rir": 2.0,
                    "scheduled_time": "07:05:00",
                    "is_cardio": False,
                },
                {
                    "id": 2,
                    "week_number": 1,
                    "day_of_week": 1,
                    "exercise_id": schedule_rules.BENCH_ID,
                    "sets": 5,
                    "reps": 5,
                    "percent_1rm": 50.0,
                    "target_weight_kg": 80.0,
                    "scheduled_time": "07:05:00",
                    "is_cardio": False,
                },
                {
                    "id": 3,
                    "week_number": 1,
                    "day_of_week": 1,
                    "exercise_id": schedule_rules.TREADMILL_RUN_ID,
                    "sets": 1,
                    "reps": 1,
                    "is_cardio": True,
                    "comment": "Quality run",
                    "details": schedule_rules.quality_intervals_details(),
                },
                {
                    "id": 4,
                    "week_number": 1,
                    "day_of_week": 1,
                    "exercise_id": None,
                    "exercise_name": "Limber 11",
                    "sets": 0,
                    "reps": 0,
                    "scheduled_time": None,
                    "is_cardio": False,
                    "type": "mobility",
                    "comment": "Limber 11",
                    "details": schedule_rules.build_stretch_routine_details("limber_11"),
                },
            ]
            """Perform get plan week rows."""

        def record_wger_export(self, *_, **__):
            pass
            """Perform record wger export."""
        """Represent StubDal."""

    class StubClient:
        base_url = "https://example.invalid"

        def __init__(self) -> None:
            self.slot_comments: list[str | None] = []
            self.entry_exercise_ids: list[int] = []
            self.entry_comments: list[str | None] = []
            self.entry_types: list[str | None] = []
            self.custom_exercises: list[tuple[str, str]] = []
            self.set_config_calls: list[tuple[str, int, int, object]] = []
            """Initialize this object."""

        def find_or_create_routine(self, **kwargs):
            return {"id": 42}
            """Perform find or create routine."""

        def delete_all_days_in_routine(self, routine_id: int) -> None:
            pass
            """Perform delete all days in routine."""

        def create_day(self, routine_id: int, order: int, name: str):
            return {"id": 100 + order, "name": name}
            """Perform create day."""

        def create_slot(self, day_id: int, order: int, comment=None):
            self.slot_comments.append(comment)
            return {"id": day_id * 10 + order}
            """Perform create slot."""

        def create_slot_entry(
            self,
            slot_id: int,
            exercise_id: int,
            order: int = 1,
            **kwargs,
        ):
            self.entry_exercise_ids.append(exercise_id)
            self.entry_comments.append(kwargs.get("comment"))
            self.entry_types.append(kwargs.get("entry_type"))
            return {"id": slot_id * 10 + order}
            """Perform create slot entry."""

        def set_config(self, config_type: str, slot_entry_id: int, iteration: int, value):
            self.set_config_calls.append((config_type, slot_entry_id, iteration, value))
            """Perform set config."""

        def ensure_custom_exercise(self, *, name: str, description: str, **kwargs):
            self.custom_exercises.append((name, description))
            return 1900
            """Perform ensure custom exercise."""
        """Represent StubClient."""

    monkeypatch.setattr("pete_e.application.services.log_utils.warn", warnings.append)
    monkeypatch.setattr("pete_e.application.services.log_utils.info", infos.append)

    client = StubClient()
    service = WgerExportService(
        dal=StubDal(),
        wger_client=client,
        validation_service=SimpleNamespace(
            validate_and_adjust_plan=lambda start_date: _make_validation_decision()
        ),
    )

    result = service.export_plan_week(
        plan_id=72,
        week_number=1,
        start_date=date(2026, 4, 20),
        force_overwrite=False,
    )

    assert result["status"] == "exported"
    assert warnings == []
    assert client.slot_comments[0].startswith("Quality run: Intervals")
    assert client.entry_comments[0].startswith("Quality run: Intervals")
    assert "Set 1 @ 50% TM (5 reps) | 80 kg | Rest 2m 30s" in client.slot_comments[1]
    assert client.entry_types[1] == "warmup"
    assert client.slot_comments[2] == "Assistance 3 x 10 | Rest 1m 15s"
    assert client.slot_comments[3].startswith("Limber 11: 11-step mobility flow")
    assert client.entry_comments[3].startswith("Limber 11: 11-step mobility flow")
    assert client.entry_exercise_ids == [
        schedule_rules.TREADMILL_RUN_ID,
        schedule_rules.BENCH_ID,
        137,
        1900,
    ]
    assert all(call[1] != 10141 for call in client.set_config_calls)
    assert client.custom_exercises
    name, description = client.custom_exercises[0]
    assert name == "Limber 11"
    assert "Source: Joe DeFranco" in description
    assert "1. Foam Roll IT Band [soft_tissue] - 10-15 passes" in description
    assert any(
        "routine 42 on https://example.invalid (days=1, slots=4, slot_entries=4)" in message
        for message in infos
    )
    """Perform test export plan week orders sessions and creates visible limber 11."""


def test_build_payload_expands_stretch_routines_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pete_e.application.services.settings.WGER_EXPAND_STRETCH_ROUTINES",
        True,
    )
    service = WgerExportService(
        dal=SimpleNamespace(),
        wger_client=SimpleNamespace(),
        validation_service=SimpleNamespace(
            validate_and_adjust_plan=lambda start_date: _make_validation_decision()
        ),
    )

    payload = service._build_payload_from_rows(
        72,
        1,
        [
            {
                "id": 1,
                "week_number": 1,
                "day_of_week": 1,
                "exercise_id": None,
                "exercise_name": "Limber 11",
                "sets": 0,
                "reps": 0,
                "is_cardio": False,
                "type": "mobility",
                "comment": "Limber 11",
                "details": schedule_rules.build_stretch_routine_details("limber_11"),
            }
        ],
        plan_start_date=date(2026, 4, 20),
    )

    exercises = payload["days"][0]["exercises"]
    assert len(exercises) == 11
    assert exercises[0]["comment"].startswith("Limber 11 1/11: Foam Roll IT Band")
    assert exercises[0]["entry_comment"] == "10-15 passes"
    """Perform test build payload expands stretch routines when enabled."""


def test_export_plan_week_warns_when_main_lift_has_no_target_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []

    class StubDal:
        def was_week_exported(self, plan_id: int, week_number: int) -> bool:
            return False
            """Perform was week exported."""

        def get_plan_week_rows(self, plan_id: int, week_number: int):
            return [
                {
                    "id": 1,
                    "week_number": 1,
                    "day_of_week": 1,
                    "exercise_id": schedule_rules.BENCH_ID,
                    "sets": 5,
                    "reps": 5,
                    "percent_1rm": 50.0,
                    "target_weight_kg": None,
                    "scheduled_time": "07:05:00",
                    "is_cardio": False,
                }
            ]
            """Perform get plan week rows."""

        def record_wger_export(self, *_, **__):
            pass
            """Perform record wger export."""
        """Represent StubDal."""

    class StubClient:
        def find_or_create_routine(self, **kwargs):
            return {"id": 42}
            """Perform find or create routine."""

        def delete_all_days_in_routine(self, routine_id: int) -> None:
            pass
            """Perform delete all days in routine."""

        def create_day(self, routine_id: int, order: int, name: str):
            return {"id": 100 + order, "name": name}
            """Perform create day."""

        def create_slot(self, day_id: int, order: int, comment=None):
            return {"id": day_id * 10 + order}
            """Perform create slot."""

        def create_slot_entry(
            self,
            slot_id: int,
            exercise_id: int,
            order: int = 1,
            **kwargs,
        ):
            return {"id": slot_id * 10 + order}
            """Perform create slot entry."""

        def set_config(self, config_type: str, slot_entry_id: int, iteration: int, value):
            return None
            """Perform set config."""
        """Represent StubClient."""

    monkeypatch.setattr("pete_e.application.services.log_utils.warn", warnings.append)

    service = WgerExportService(
        dal=StubDal(),
        wger_client=StubClient(),
        validation_service=SimpleNamespace(
            validate_and_adjust_plan=lambda start_date: _make_validation_decision()
        ),
    )

    result = service.export_plan_week(
        plan_id=72,
        week_number=1,
        start_date=date(2026, 4, 20),
        force_overwrite=False,
    )

    assert result["status"] == "exported"
    assert any("Skipping weight config for main lift due to missing target weight" in message for message in warnings)
    """Perform test export plan week warns when main lift has no target weight."""


def test_run_end_to_end_week_passes_cached_validation() -> None:
    decision = _make_validation_decision("All clear")

    class RecordingValidationService:
        def __init__(self, decision: ValidationDecision):
            self.decision = decision
            self.calls: list[date] = []
            """Initialize this object."""

        def validate_and_adjust_plan(self, week_start: date) -> ValidationDecision:
            self.calls.append(week_start)
            return self.decision
            """Perform validate and adjust plan."""
        """Represent RecordingValidationService."""

    class StubPlanService:
        def __init__(self) -> None:
            self.created: list[date] = []
            """Initialize this object."""

        def create_next_plan_for_cycle(self, *, start_date: date) -> int:
            self.created.append(start_date)
            return 99
            """Perform create next plan for cycle."""
        """Represent StubPlanService."""

    class RecordingExportService:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, date, ValidationDecision | None]] = []
            """Initialize this object."""

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
            """Perform export plan week."""
        """Represent RecordingExportService."""

    class StubDal:
        def get_active_plan(self):
            return {"start_date": date(2024, 5, 6), "weeks": 4}
            """Perform get active plan."""

        def close(self) -> None:  # pragma: no cover - unused
            pass
            """Perform close."""
        """Represent StubDal."""

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
    """Perform test run end to end week passes cached validation."""
