"""Orchestrator contracts around the application-owned summary boundary."""

from __future__ import annotations

from datetime import date
from types import MethodType

import pytest

from pete_e.application.exceptions import ApplicationError, DataAccessError
from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator


TARGET = date(2026, 8, 23)


class _Dal:
    def get_metrics_overview(self, target_date: date):
        return ["metric_name", "yesterday_value"], [("weight", 82.0)]

    def get_nutrition_daily_summary(self, target_date: date):
        return {"meals_logged": 0}


class _Narrative:
    def build_daily_narrative(self, payload: dict[str, object]) -> str:
        return "base narrative  \n"


class _Voice:
    def __init__(self) -> None:
        self.compose_calls: list[tuple[object, str]] = []

    def compose(self, request: object, *, fallback_message: str) -> str:
        self.compose_calls.append((request, fallback_message))
        return "voiced summary"


def _orchestrator(
    *,
    dal: object | None = None,
    narrative: object | None = None,
    voice: object | None = None,
) -> Orchestrator:
    orchestrator = object.__new__(Orchestrator)
    orchestrator.dal = dal or _Dal()
    orchestrator.narrative_builder = narrative or _Narrative()
    orchestrator.voice_service = voice or _Voice()
    orchestrator._build_morning_training_guidance = MethodType(
        lambda self, **kwargs: None,
        orchestrator,
    )
    orchestrator._build_nutrition_summary_line = MethodType(
        lambda self, target: None,
        orchestrator,
    )
    orchestrator._build_daily_supplemental_lines = MethodType(
        lambda self, target: [],
        orchestrator,
    )
    orchestrator._load_coach_state_context = MethodType(
        lambda self, target: {},
        orchestrator,
    )
    return orchestrator


def test_deterministic_get_summary_does_not_invoke_voice() -> None:
    class _ExplodingVoice:
        def compose(self, request: object, *, fallback_message: str) -> str:
            raise AssertionError("voice must not run")

    orchestrator = _orchestrator(voice=_ExplodingVoice())

    assert orchestrator.get_daily_summary(TARGET) == "base narrative"


def test_message_builder_uses_rewrite_when_compose_is_unavailable() -> None:
    calls: list[str] = []

    class _RewriteOnly:
        compose = None

        def rewrite(self, fallback_message: str) -> str:
            calls.append(fallback_message)
            return "rewritten summary"

    orchestrator = _orchestrator(voice=_RewriteOnly())

    assert orchestrator.build_daily_summary_message(TARGET) == "rewritten summary"
    assert calls == ["base narrative"]


def test_draft_order_and_structured_voice_facts_are_preserved() -> None:
    voice = _Voice()
    orchestrator = _orchestrator(voice=voice)
    orchestrator._build_morning_training_guidance = MethodType(
        lambda self, **kwargs: "training guidance",
        orchestrator,
    )
    orchestrator._build_nutrition_summary_line = MethodType(
        lambda self, target: "nutrition line",
        orchestrator,
    )
    orchestrator._build_daily_supplemental_lines = MethodType(
        lambda self, target: ["body age", "muscle", "hrv", "trends"],
        orchestrator,
    )
    orchestrator._load_coach_state_context = MethodType(
        lambda self, target: {
            "profile": {"display_name": "Ric", "timezone": "Europe/London"},
            "summary": {"readiness_state": "ready"},
            "coaching_notes": ["keep easy"],
            "goal_state": {"goal": "race"},
        },
        orchestrator,
    )

    assert orchestrator.build_daily_summary_message(TARGET) == "voiced summary"

    request, fallback = voice.compose_calls[0]
    assert fallback == (
        "base narrative\n\ntraining guidance\n\nnutrition line\n"
        "body age\nmuscle\nhrv\ntrends"
    )
    assert request.message_type == "daily_summary"
    assert request.dates == {
        "report_date": "2026-08-23",
        "action_date": "2026-08-23",
    }
    assert [fact.id for fact in request.must_include_facts] == [
        "training_guidance",
        "nutrition_summary",
        "supplemental_context_1",
        "supplemental_context_2",
        "supplemental_context_3",
        "supplemental_context_4",
    ]
    assert request.deterministic_decisions == {
        "readiness_state": "ready",
        "morning_training_guidance": "training guidance",
    }
    assert request.constraints_and_warnings == ["keep easy"]


def test_default_report_and_action_dates_remain_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return cls(2026, 8, 24)

    voice = _Voice()
    orchestrator = _orchestrator(voice=voice)
    monkeypatch.setattr(orchestrator_module, "date", _FixedDate)

    orchestrator.build_daily_summary_message()

    request, _fallback = voice.compose_calls[0]
    assert request.dates == {
        "report_date": "2026-08-23",
        "action_date": "2026-08-24",
    }


def test_metrics_application_error_is_reraised_unchanged() -> None:
    error = ApplicationError("owned failure")

    class _FailingDal:
        def get_metrics_overview(self, target_date: date):
            raise error

    with pytest.raises(ApplicationError) as caught:
        _orchestrator(dal=_FailingDal()).get_daily_summary(TARGET)

    assert caught.value is error


def test_metrics_unknown_error_is_logged_and_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs: list[str] = []

    class _FailingDal:
        def get_metrics_overview(self, target_date: date):
            raise OSError("database offline")

    monkeypatch.setattr(
        orchestrator_module.log_utils,
        "error",
        lambda message: logs.append(message),
    )

    with pytest.raises(DataAccessError) as caught:
        _orchestrator(dal=_FailingDal()).get_daily_summary(TARGET)

    assert str(caught.value) == (
        "Failed to load metrics overview for 2026-08-23: database offline"
    )
    assert isinstance(caught.value.__cause__, OSError)
    assert logs == [str(caught.value)]


def test_narrative_error_is_logged_and_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs: list[str] = []

    class _FailingNarrative:
        def build_daily_narrative(self, payload: dict[str, object]) -> str:
            raise ValueError("bad metrics")

    monkeypatch.setattr(
        orchestrator_module.log_utils,
        "error",
        lambda message: logs.append(message),
    )

    with pytest.raises(ApplicationError) as caught:
        _orchestrator(narrative=_FailingNarrative()).get_daily_summary(TARGET)

    assert (
        str(caught.value)
        == "Failed to build daily narrative for 2026-08-23: bad metrics"
    )
    assert isinstance(caught.value.__cause__, ValueError)
    assert logs == [str(caught.value)]
