from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List

from pete_e.application.collaborator_contracts import SyncContract
from pete_e.application.exceptions import ApplicationError
from pete_e.infrastructure import log_utils


@dataclass(frozen=True)
class DailyAutomationResult:
    ingest_success: bool
    failed_sources: List[str] = field(default_factory=list)
    source_statuses: Dict[str, str] = field(default_factory=dict)
    summary_target: date | None = None
    summary_attempted: bool = False
    summary_sent: bool = False
    undelivered_alerts: List[str] = field(default_factory=list)


class DailySyncWorkflow:
    def __init__(self, *, daily_sync_service: SyncContract, send_message):
        self.daily_sync_service = daily_sync_service
        self.send_message = send_message

    def run_daily_sync(self, days: int):
        log_utils.info("Orchestrator running daily sync...")
        result = self.daily_sync_service.run_full(days=days)
        return result.as_tuple()

    def run(self, *, days: int = 1, summary_date: date | None = None, orchestrator=None) -> DailyAutomationResult:
        success, failures, statuses, alerts = self.run_daily_sync(days=days)
        summary_target = summary_date or (date.today() - timedelta(days=1))
        summary_attempted = bool(success and (summary_date is not None or days == 1))
        summary_sent = False

        if summary_attempted:
            try:
                from pete_e.cli.messenger import build_daily_summary

                summary_text = build_daily_summary(orchestrator=orchestrator, target_date=summary_target)
                if summary_text.strip():
                    summary_sent = self.send_message(summary_text)
                else:
                    log_utils.warn(
                        f"Skipping Telegram summary for {summary_target.isoformat()} because it was empty."
                    )
            except ApplicationError:
                raise
            except Exception as exc:  # pragma: no cover
                log_utils.error(f"Failed to send daily summary for {summary_target.isoformat()}: {exc}")

        return DailyAutomationResult(
            ingest_success=bool(success),
            failed_sources=list(failures or []),
            source_statuses=dict(statuses or {}),
            summary_target=summary_target,
            summary_attempted=summary_attempted,
            summary_sent=summary_sent,
            undelivered_alerts=list(alerts or []),
        )
