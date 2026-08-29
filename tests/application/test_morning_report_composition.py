"""Production composition contract for the morning-report operation."""

from __future__ import annotations

from datetime import date

import pytest

from pete_e.api_routes import dependencies
from pete_e.application import composition
from pete_e.application.adapter_contracts import NotificationDeliveryResult
from pete_e.application.morning_report import MorningReportResult
from pete_e.application import orchestrator as orchestrator_module


def test_production_composition_uses_established_builder_and_notification_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []
    telegram_client = object()

    class _SummaryBuilder:
        def build_daily_summary_message(self, target_date: date | None = None) -> str:
            events.append(("build", target_date))
            return "Composed report"

        def close(self) -> None:
            events.append(("close", True))

    class _NotificationChannel:
        def send(self, message: object) -> NotificationDeliveryResult:
            events.append(("send", message))
            return NotificationDeliveryResult(channel="telegram", success=True)

    def _provide_channel(*, client: object) -> _NotificationChannel:
        assert client is telegram_client
        events.append(("compose_channel", client))
        return _NotificationChannel()

    monkeypatch.setattr(
        composition,
        "provide_telegram_notification_channel",
        _provide_channel,
    )

    operation = composition.provide_morning_report_operation(
        summary_builder=_SummaryBuilder(),
        telegram_client=telegram_client,  # type: ignore[arg-type]
    )
    result = operation.execute(target_date=date(2026, 8, 23), send=True)

    assert result == MorningReportResult(
        report="Composed report",
        target_date="2026-08-23",
        sent=True,
    )
    assert [name for name, _value in events] == [
        "compose_channel",
        "build",
        "send",
    ]
    assert not any(name == "close" for name, _value in events)


def test_api_callback_boundary_builds_fresh_production_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []
    telegram_client = object()
    expected_operation = object()

    class _Orchestrator:
        def __init__(self) -> None:
            events.append(("orchestrator", self))
            self.telegram_client = telegram_client

        def build_daily_summary_message(self, target_date: date | None = None) -> str:
            return "unused"

        def close(self) -> None:
            events.append(("close", True))

    def _provide_operation(
        *,
        summary_builder: object,
        telegram_client: object,
    ) -> object:
        events.append(("provider_builder", summary_builder))
        events.append(("provider_client", telegram_client))
        return expected_operation

    monkeypatch.setattr(orchestrator_module, "Orchestrator", _Orchestrator)
    monkeypatch.setattr(
        composition,
        "provide_morning_report_operation",
        _provide_operation,
    )

    result = dependencies.get_morning_report_operation()

    assert result is expected_operation
    assert [name for name, _value in events] == [
        "orchestrator",
        "provider_builder",
        "provider_client",
    ]
    assert events[1][1] is events[0][1]
    assert events[2][1] is telegram_client
