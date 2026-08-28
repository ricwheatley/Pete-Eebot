"""Pure tests for the application-owned weekly-plan message boundary."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import FrozenInstanceError
from datetime import date
from typing import Any

import pytest

from pete_e.application.weekly_plan_message import (
    LegacyWeeklyPlanReader,
    WeeklyPlanPresentationService,
    resolve_weekly_plan_target,
    select_legacy_weekly_plan_reader,
    select_legacy_weekly_plan_voice,
    weekly_plan_required_terms,
)


class _Reader:
    def __init__(
        self,
        *,
        active_plan: Mapping[str, Any] | None = None,
        rows: Iterable[Mapping[str, Any]] | None = None,
    ) -> None:
        self.active_plan = active_plan or {
            "id": 7,
            "start_date": date(2024, 9, 2),
            "weeks": 2,
        }
        self.rows = rows or [{"day_of_week": 1, "exercise_name": "Squat"}]

    def get_active_plan(self) -> Mapping[str, Any] | None:
        return self.active_plan

    def get_plan_week(
        self,
        plan_id: object,
        week_number: int,
    ) -> Iterable[Mapping[str, Any]] | None:
        assert (plan_id, week_number) == (7, 1)
        return self.rows


class _Renderer:
    def build_weekly_plan(
        self,
        plan_week_data: Iterable[Mapping[str, Any]],
        week_number: int,
        week_start: date | None = None,
    ) -> str:
        assert list(plan_week_data) == [{"day_of_week": 1, "exercise_name": "Squat"}]
        assert (week_number, week_start) == (1, date(2024, 9, 2))
        return "fallback"


class _Voice:
    def __init__(self) -> None:
        self.request: object | None = None

    def compose(self, request: object, *, fallback_message: str) -> str:
        self.request = request
        assert fallback_message == "fallback"
        return "voiced"


def test_target_selection_is_explicit_and_sunday_only_affects_default() -> None:
    monday = date(2024, 9, 9)
    sunday = date(2024, 9, 8)

    assert resolve_weekly_plan_target(target_date=monday, current_date=sunday) == monday
    assert resolve_weekly_plan_target(target_date=None, current_date=sunday) == monday
    assert resolve_weekly_plan_target(target_date=None, current_date=monday) == monday


def test_service_uses_injected_clock_default_logger_and_typed_ports() -> None:
    service = WeeklyPlanPresentationService(
        reader=_Reader(active_plan={"id": 7, "start_date": "invalid", "weeks": 2}),
        renderer=_Renderer(),
        today=lambda: date(2024, 9, 2),
    )

    assert (
        service.build_message() == "The active training plan has an invalid start date."
    )
    with pytest.raises(FrozenInstanceError):
        service.reader = None  # type: ignore[misc]


def test_voice_without_coach_state_provider_uses_empty_state() -> None:
    voice = _Voice()
    service = WeeklyPlanPresentationService(
        reader=_Reader(),
        renderer=_Renderer(),
        voice_composer=voice,
        today=lambda: date(2024, 9, 2),
    )

    assert service.build_message() == "voiced"
    assert voice.request is not None
    assert voice.request.coach_state == {}


def test_required_terms_skip_non_dicts_before_deduplication_and_cap() -> None:
    rows: list[object] = [
        SimpleMapping("ignored"),
        None,
        {"exercise_name": " Press "},
        {"exercise_name": "Press"},
        {"exercise_name": 12},
    ]
    assert weekly_plan_required_terms(rows) == ["Press", "12"]


class SimpleMapping(Mapping[str, object]):
    """A non-dict mapping remains outside the legacy required-term rule."""

    def __init__(self, value: object) -> None:
        self.value = value

    def __getitem__(self, key: str) -> object:
        if key != "exercise_name":
            raise KeyError(key)
        return self.value

    def __iter__(self):
        return iter(("exercise_name",))

    def __len__(self) -> int:
        return 1


def test_legacy_reader_adapter_contract_and_preference() -> None:
    calls: list[str] = []

    class Source:
        def get_active_plan(self) -> dict[str, object]:
            return {"id": 3}

        def get_plan_week(self, plan_id: object, week_number: int) -> tuple[str]:
            calls.append(f"preferred:{plan_id}:{week_number}")
            return ("preferred",)

        def get_plan_week_rows(self, plan_id: object, week_number: int) -> tuple[str]:
            calls.append(f"rows:{plan_id}:{week_number}")
            return ("rows",)

    reader = select_legacy_weekly_plan_reader(Source())
    assert isinstance(reader, LegacyWeeklyPlanReader)
    assert reader.get_active_plan() == {"id": 3}
    assert tuple(reader.get_plan_week("raw", 4) or ()) == ("preferred",)
    assert calls == ["preferred:raw:4"]
    assert select_legacy_weekly_plan_reader(None) is None
    assert select_legacy_weekly_plan_reader(object()) is None
    assert (
        select_legacy_weekly_plan_reader(
            type("OnlyActive", (), {"get_active_plan": lambda self: {}})()
        )
        is None
    )


def test_legacy_voice_adapter_contract() -> None:
    assert select_legacy_weekly_plan_voice(None) is None
    assert select_legacy_weekly_plan_voice(object()) is None
    assert (
        select_legacy_weekly_plan_voice(type("NonCallable", (), {"compose": None})())
        is None
    )

    class Voice:
        def compose(self, request: object, *, fallback_message: str) -> object:
            assert request == "request"
            assert fallback_message == "fallback"
            return None

    selected = select_legacy_weekly_plan_voice(Voice())
    assert selected is not None
    assert selected.compose("request", fallback_message="fallback") is None  # type: ignore[arg-type,comparison-overlap]
