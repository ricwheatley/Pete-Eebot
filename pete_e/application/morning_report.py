"""Typed application operation for building and optionally sending a morning report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pete_e.application.adapter_contracts import (
    NotificationChannel,
    NotificationMessage,
)
from pete_e.application.daily_summary import DailySummaryMessageBuilder


@dataclass(frozen=True, slots=True)
class MorningReportResult:
    """Completed morning-report values shared by delivery and presentation adapters."""

    report: str
    target_date: str | None
    sent: bool
    success: bool = True

    def summary_line(self) -> str:
        """Return the established operator-facing result sentence."""

        if not self.report.strip():
            return "No morning report is available yet. Give the sync a minute."
        action = "sent" if self.sent else "generated"
        date_fragment = f" for {self.target_date}" if self.target_date else ""
        return f"Morning report {action}{date_fragment}."


class MorningReportOperation:
    """Own the report construction and optional notification decision."""

    def __init__(
        self,
        *,
        summary_builder: DailySummaryMessageBuilder,
        notification_channel: NotificationChannel,
    ) -> None:
        self._summary_builder = summary_builder
        self._notification_channel = notification_channel

    def execute(
        self,
        *,
        target_date: date | None,
        send: bool,
    ) -> MorningReportResult:
        """Build a report and send only a requested, non-blank result."""

        value = self._summary_builder.build_daily_summary_message(
            target_date=target_date
        )
        report = "" if value is None else str(value)
        sent = False
        if send and report.strip():
            delivery = self._notification_channel.send(NotificationMessage(body=report))
            if not delivery.success:
                raise RuntimeError("Telegram send for morning report failed.")
            sent = True

        return MorningReportResult(
            report=report,
            target_date=target_date.isoformat() if target_date else None,
            sent=sent,
        )


__all__ = ["MorningReportOperation", "MorningReportResult"]
