"""Typed application use case for generic operator message previews."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from pete_e.application.daily_summary import DailySummaryMessageBuilder
from pete_e.application.weekly_plan_message import WeeklyPlanMessageBuilder


class MessageType(StrEnum):
    """Supported generic message families."""

    SUMMARY = "summary"
    TRAINER = "trainer"
    PLAN = "plan"


_MESSAGE_TYPE_LABELS = {
    MessageType.SUMMARY: "Daily summary",
    MessageType.TRAINER: "Trainer check-in",
    MessageType.PLAN: "Weekly plan",
}


class TrainerMessageBuilder(Protocol):
    """Build the established trainer message for an optional day."""

    def build_trainer_message(self, message_date: date | None = None) -> str: ...


@dataclass(frozen=True, slots=True)
class MessagePreviewResult:
    """Generated preview values consumed by job and presentation adapters."""

    message_type: MessageType
    message: str
    success: bool = True

    def summary_line(self) -> str:
        """Return the established operator-facing result sentence."""

        label = _MESSAGE_TYPE_LABELS[self.message_type]
        if not self.message.strip():
            return f"No {label.lower()} message is available."
        return f"{label} preview generated."


class MessagePreviewService:
    """Select exactly one established application-owned message builder."""

    def __init__(
        self,
        *,
        summary_builder: DailySummaryMessageBuilder,
        trainer_builder: TrainerMessageBuilder,
        weekly_builder: WeeklyPlanMessageBuilder,
    ) -> None:
        self._summary_builder = summary_builder
        self._trainer_builder = trainer_builder
        self._weekly_builder = weekly_builder

    def preview(self, message_type: MessageType) -> MessagePreviewResult:
        """Build and normalize one selected message without sending it."""

        selected = MessageType(message_type)
        if selected is MessageType.SUMMARY:
            value = self._summary_builder.build_daily_summary_message()
        elif selected is MessageType.TRAINER:
            value = self._trainer_builder.build_trainer_message()
        else:
            value = self._weekly_builder.build_message()
        return MessagePreviewResult(selected, "" if value is None else str(value))


__all__ = [
    "MessagePreviewResult",
    "MessagePreviewService",
    "MessageType",
    "TrainerMessageBuilder",
]
