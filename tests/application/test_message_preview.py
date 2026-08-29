"""Pure tests for the typed generic-message preview use case."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pete_e.application.message_preview import (
    MessagePreviewResult,
    MessagePreviewService,
    MessageType,
)


class _Builders:
    def __init__(self) -> None:
        self.values: dict[MessageType, object] = {
            MessageType.SUMMARY: "summary",
            MessageType.TRAINER: "trainer",
            MessageType.PLAN: "plan",
        }
        self.calls: list[MessageType] = []

    def _build(self, message_type: MessageType) -> Any:
        self.calls.append(message_type)
        value = self.values[message_type]
        if isinstance(value, Exception):
            raise value
        return value

    def build_daily_summary_message(self, target_date=None) -> Any:
        assert target_date is None
        return self._build(MessageType.SUMMARY)

    def build_trainer_message(self, message_date=None) -> Any:
        assert message_date is None
        return self._build(MessageType.TRAINER)

    def build_message(self, *, target_date=None, current_date=None) -> Any:
        assert target_date is None
        assert current_date is None
        return self._build(MessageType.PLAN)


def _service(builders: _Builders) -> MessagePreviewService:
    return MessagePreviewService(
        summary_builder=builders,
        trainer_builder=builders,
        weekly_builder=builders,
    )


def test_message_type_values_are_the_stable_public_names() -> None:
    assert tuple(MessageType) == (
        MessageType.SUMMARY,
        MessageType.TRAINER,
        MessageType.PLAN,
    )
    assert [message_type.value for message_type in MessageType] == [
        "summary",
        "trainer",
        "plan",
    ]


def test_invalid_type_is_rejected_at_the_application_boundary() -> None:
    builders = _Builders()

    with pytest.raises(ValueError, match="not a valid MessageType"):
        _service(builders).preview(cast(MessageType, "invalid"))

    assert builders.calls == []


@pytest.mark.parametrize("message_type", list(MessageType))
def test_preview_selects_exactly_one_established_builder(
    message_type: MessageType,
) -> None:
    builders = _Builders()

    result = _service(builders).preview(message_type)

    assert result == MessagePreviewResult(message_type, message_type.value)
    assert builders.calls == [message_type]


@pytest.mark.parametrize("message_type", list(MessageType))
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("Text", "Text"),
        (27, "27"),
        (SimpleNamespace(answer=42), "namespace(answer=42)"),
        (" \n", " \n"),
    ],
)
def test_preview_normalizes_builder_values_without_trimming(
    message_type: MessageType,
    value: object,
    expected: str,
) -> None:
    builders = _Builders()
    builders.values[message_type] = value

    result = _service(builders).preview(message_type)

    assert result.message == expected
    assert result.success is True


@pytest.mark.parametrize(
    ("message_type", "message", "expected"),
    [
        (MessageType.SUMMARY, "Text", "Daily summary preview generated."),
        (MessageType.TRAINER, "Text", "Trainer check-in preview generated."),
        (MessageType.PLAN, "Text", "Weekly plan preview generated."),
        (
            MessageType.SUMMARY,
            " \n",
            "No daily summary message is available.",
        ),
        (
            MessageType.TRAINER,
            "",
            "No trainer check-in message is available.",
        ),
        (MessageType.PLAN, "\t", "No weekly plan message is available."),
    ],
)
def test_result_summary_lines_are_exact(
    message_type: MessageType,
    message: str,
    expected: str,
) -> None:
    result = MessagePreviewResult(message_type, message)

    assert result.summary_line() == expected


def test_result_is_frozen() -> None:
    result = MessagePreviewResult(MessageType.SUMMARY, "Text")

    with pytest.raises(FrozenInstanceError):
        result.message = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("message_type", list(MessageType))
def test_selected_builder_exception_propagates_unchanged(
    message_type: MessageType,
) -> None:
    builders = _Builders()
    error = RuntimeError(f"{message_type.value} failed")
    builders.values[message_type] = error

    with pytest.raises(RuntimeError, match=f"{message_type.value} failed") as caught:
        _service(builders).preview(message_type)

    assert caught.value is error
    assert builders.calls == [message_type]
