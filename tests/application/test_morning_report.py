"""Pure tests for the typed morning-report application operation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from pete_e.application.adapter_contracts import (
    AdapterHealth,
    AdapterMetadata,
    NotificationDeliveryResult,
    NotificationMessage,
)
from pete_e.application.morning_report import (
    MorningReportOperation,
    MorningReportResult,
)


TARGET = date(2026, 8, 23)


class _Builder:
    def __init__(self, value: object = "Report") -> None:
        self.value = value
        self.targets: list[date | None] = []

    def build_daily_summary_message(self, target_date: date | None = None) -> Any:
        self.targets.append(target_date)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _Channel:
    def __init__(
        self,
        result: NotificationDeliveryResult | Exception | None = None,
    ) -> None:
        self.result = result or NotificationDeliveryResult(
            channel="test",
            success=True,
        )
        self.messages: list[NotificationMessage] = []

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(name="test", kind="notification_channel")

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(status="ok", detail="ready")

    def send(self, message: NotificationMessage) -> NotificationDeliveryResult:
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _operation(
    builder: _Builder,
    channel: _Channel,
) -> MorningReportOperation:
    return MorningReportOperation(
        summary_builder=builder,
        notification_channel=channel,
    )


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            MorningReportResult("", None, False),
            "No morning report is available yet. Give the sync a minute.",
        ),
        (
            MorningReportResult("Report", None, False),
            "Morning report generated.",
        ),
        (
            MorningReportResult("Report", "2026-08-23", False),
            "Morning report generated for 2026-08-23.",
        ),
        (
            MorningReportResult("Report", None, True),
            "Morning report sent.",
        ),
        (
            MorningReportResult("Report", "2026-08-23", True),
            "Morning report sent for 2026-08-23.",
        ),
    ],
)
def test_result_summary_lines_are_exact(
    result: MorningReportResult,
    expected: str,
) -> None:
    assert result.summary_line() == expected
    assert result.success is True


def test_result_is_frozen() -> None:
    result = MorningReportResult("Report", None, False)

    with pytest.raises(FrozenInstanceError):
        result.report = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("Report", "Report"),
        (27, "27"),
        (SimpleNamespace(answer=42), "namespace(answer=42)"),
    ],
)
def test_preview_converts_unusual_builder_values_and_never_sends(
    value: object,
    expected: str,
) -> None:
    builder = _Builder(value)
    channel = _Channel()

    result = _operation(builder, channel).execute(target_date=TARGET, send=False)

    assert result == MorningReportResult(
        report=expected,
        target_date="2026-08-23",
        sent=False,
    )
    assert builder.targets == [TARGET]
    assert channel.messages == []


@pytest.mark.parametrize("report", ["", " ", "\n\t"])
def test_send_skips_blank_reports(report: str) -> None:
    channel = _Channel()

    result = _operation(_Builder(report), channel).execute(
        target_date=None,
        send=True,
    )

    assert result == MorningReportResult(report=report, target_date=None, sent=False)
    assert result.summary_line() == (
        "No morning report is available yet. Give the sync a minute."
    )
    assert channel.messages == []


def test_send_delivers_non_blank_report_with_the_existing_message_contract() -> None:
    channel = _Channel()

    result = _operation(_Builder("Send this"), channel).execute(
        target_date=TARGET,
        send=True,
    )

    assert result == MorningReportResult(
        report="Send this",
        target_date="2026-08-23",
        sent=True,
    )
    assert channel.messages == [NotificationMessage(body="Send this")]


def test_false_notification_delivery_has_the_exact_compatibility_error() -> None:
    channel = _Channel(
        NotificationDeliveryResult(
            channel="telegram",
            success=False,
            error="offline",
        )
    )

    with pytest.raises(
        RuntimeError,
        match=r"^Telegram send for morning report failed\.$",
    ):
        _operation(_Builder("Send this"), channel).execute(
            target_date=None,
            send=True,
        )

    assert channel.messages == [NotificationMessage(body="Send this")]


def test_notification_exception_propagates_unchanged() -> None:
    error = OSError("network down")
    channel = _Channel(error)

    with pytest.raises(OSError, match="network down") as caught:
        _operation(_Builder("Send this"), channel).execute(
            target_date=None,
            send=True,
        )

    assert caught.value is error


def test_builder_exception_propagates_before_notification() -> None:
    error = ValueError("builder failed")
    builder = _Builder(error)
    channel = _Channel()

    with pytest.raises(ValueError, match="builder failed") as caught:
        _operation(builder, channel).execute(target_date=TARGET, send=True)

    assert caught.value is error
    assert channel.messages == []
