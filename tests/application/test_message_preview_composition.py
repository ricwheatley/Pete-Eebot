"""Production composition contracts for generic message previews."""

from __future__ import annotations

import pytest

from pete_e.api_routes import dependencies
from pete_e.application import composition
from pete_e.application.message_preview import MessagePreviewService, MessageType
from pete_e.application import orchestrator as orchestrator_module


class _Builders:
    def build_daily_summary_message(self, target_date=None) -> str:
        return "summary"

    def build_trainer_message(self, message_date=None) -> str:
        return "trainer"

    def build_message(self, *, target_date=None, current_date=None) -> str:
        return "plan"


def test_application_composition_passes_all_three_explicit_builder_ports() -> None:
    builders = _Builders()

    service = composition.provide_message_preview_service(
        summary_builder=builders,
        trainer_builder=builders,
        weekly_builder=builders,
    )

    assert service.preview(MessageType.SUMMARY).message == "summary"
    assert service.preview(MessageType.TRAINER).message == "trainer"
    assert service.preview(MessageType.PLAN).message == "plan"


def test_api_callback_boundary_builds_a_fresh_service_without_closing_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []
    weekly_builder = object()
    services = iter((object(), object()))

    class _Orchestrator:
        def __init__(self) -> None:
            self.weekly_plan_message_builder = weekly_builder
            events.append(("orchestrator", self))

        def close(self) -> None:
            events.append(("close", self))

    def _provide(**builders: object) -> object:
        events.extend((name, value) for name, value in builders.items())
        return next(services)

    monkeypatch.setattr(orchestrator_module, "Orchestrator", _Orchestrator)
    monkeypatch.setattr(composition, "provide_message_preview_service", _provide)

    first = dependencies.get_message_preview_service()
    second = dependencies.get_message_preview_service()

    assert first is not second
    assert [name for name, _value in events] == [
        "orchestrator",
        "summary_builder",
        "trainer_builder",
        "weekly_builder",
        "orchestrator",
        "summary_builder",
        "trainer_builder",
        "weekly_builder",
    ]
    assert events[1][1] is events[0][1]
    assert events[2][1] is events[0][1]
    assert events[3][1] is weekly_builder
    assert events[5][1] is events[4][1]
    assert events[6][1] is events[4][1]
    assert events[7][1] is weekly_builder
    assert not any(name == "close" for name, _value in events)


def test_composition_returns_the_typed_preview_service() -> None:
    builders = _Builders()

    service = composition.provide_message_preview_service(
        summary_builder=builders,
        trainer_builder=builders,
        weekly_builder=builders,
    )

    assert isinstance(service, MessagePreviewService)
