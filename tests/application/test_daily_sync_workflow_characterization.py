"""Pre-extraction contracts for daily automation summary handling."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from pete_e.application.exceptions import DataAccessError
from pete_e.application.workflows import daily_sync as daily_sync_module
from pete_e.application.workflows.daily_sync import (
    DailyAutomationResult,
    DailySyncWorkflow,
)


TARGET = date(2026, 8, 23)


class _SyncService:
    def __init__(
        self,
        *,
        success: bool = True,
        failures: tuple[str, ...] = (),
        statuses: dict[str, str] | None = None,
        alerts: tuple[str, ...] = (),
    ) -> None:
        self.result = (success, failures, statuses or {}, alerts)
        self.days: list[int] = []

    def run_full(self, *, days: int):
        self.days.append(days)
        return SimpleNamespace(as_tuple=lambda: self.result)


class _SummaryBuilder:
    def __init__(self, callback=None) -> None:
        self.callback = callback or (lambda target_date: "summary")
        self.targets: list[date | None] = []

    def build_daily_summary_message(self, target_date: date | None = None) -> str:
        self.targets.append(target_date)
        return self.callback(target_date)


def _workflow(
    service: _SyncService,
    sent: list[str],
    *,
    send_result: bool = True,
    summary_builder: _SummaryBuilder | None = None,
) -> DailySyncWorkflow:
    return DailySyncWorkflow(
        daily_sync_service=service,
        send_message=lambda message: sent.append(message) or send_result,
        summary_builder=summary_builder or _SummaryBuilder(),
    )


def test_successful_explicit_summary_preserves_result_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _SyncService(
        failures=("Withings",),
        statuses={"Withings": "partial", "Apple": "ok"},
        alerts=("alert-a",),
    )
    sent: list[str] = []
    builder = _SummaryBuilder()

    result = _workflow(service, sent, summary_builder=builder).run(
        days=3,
        summary_date=TARGET,
        orchestrator=object(),
    )

    assert result == DailyAutomationResult(
        ingest_success=True,
        failed_sources=["Withings"],
        source_statuses={"Withings": "partial", "Apple": "ok"},
        summary_target=TARGET,
        summary_attempted=True,
        summary_sent=True,
        undelivered_alerts=["alert-a"],
    )
    assert service.days == [3]
    assert builder.targets == [TARGET]
    assert sent == ["summary"]


def test_default_yesterday_is_used_for_one_day_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return cls(2026, 8, 24)

    builder = _SummaryBuilder()
    monkeypatch.setattr(daily_sync_module, "date", _FixedDate)

    result = _workflow(_SyncService(), [], summary_builder=builder).run(
        days=1,
        orchestrator=object(),
    )

    assert result.summary_target == TARGET
    assert result.summary_attempted is True
    assert builder.targets == [TARGET]


@pytest.mark.parametrize(
    ("success", "days"),
    [(False, 1), (True, 2), (False, 2)],
)
def test_summary_attempt_rule_skips_builder(
    monkeypatch: pytest.MonkeyPatch,
    success: bool,
    days: int,
) -> None:
    builder = _SummaryBuilder(
        lambda target_date: (_ for _ in ()).throw(AssertionError("must not build"))
    )

    result = _workflow(
        _SyncService(success=success),
        [],
        summary_builder=builder,
    ).run(
        days=days,
        orchestrator=object(),
    )

    assert result.summary_attempted is False
    assert result.summary_sent is False
    assert result.ingest_success is success
    assert builder.targets == []


def test_explicit_date_attempts_summary_for_multi_day_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _workflow(_SyncService(), []).run(
        days=14,
        summary_date=TARGET,
        orchestrator=object(),
    )

    assert result.summary_attempted is True


@pytest.mark.parametrize("report", [None, "", " \n"])
def test_empty_report_warns_without_sending(
    monkeypatch: pytest.MonkeyPatch,
    report: object,
) -> None:
    warnings: list[str] = []
    sent: list[str] = []
    builder = _SummaryBuilder(lambda target_date: report)
    monkeypatch.setattr(
        daily_sync_module.log_utils,
        "warn",
        lambda message: warnings.append(message),
    )

    result = _workflow(_SyncService(), sent, summary_builder=builder).run(
        summary_date=TARGET,
        orchestrator=object(),
    )

    assert result.summary_sent is False
    assert sent == []
    assert warnings == [
        "Skipping Telegram summary for 2026-08-23 because it was empty."
    ]


def test_application_error_from_builder_is_reraised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = DataAccessError("database unavailable")
    builder = _SummaryBuilder(lambda target_date: (_ for _ in ()).throw(error))

    with pytest.raises(DataAccessError) as caught:
        _workflow(_SyncService(), [], summary_builder=builder).run(
            orchestrator=object()
        )

    assert caught.value is error


def test_non_application_builder_error_is_logged_and_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    builder = _SummaryBuilder(
        lambda target_date: (_ for _ in ()).throw(RuntimeError("broken builder"))
    )
    monkeypatch.setattr(
        daily_sync_module.log_utils,
        "error",
        lambda message: errors.append(message),
    )

    result = _workflow(_SyncService(), [], summary_builder=builder).run(
        summary_date=TARGET,
        orchestrator=object(),
    )

    assert result.summary_attempted is True
    assert result.summary_sent is False
    assert errors == ["Failed to send daily summary for 2026-08-23: broken builder"]


def test_false_sender_result_is_returned_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _workflow(_SyncService(), [], send_result=False).run(
        summary_date=TARGET,
        orchestrator=object(),
    )

    assert result.summary_sent is False


def test_non_string_builder_value_is_converted_before_send() -> None:
    sent: list[str] = []
    builder = _SummaryBuilder(lambda target_date: 27)

    result = _workflow(
        _SyncService(),
        sent,
        summary_builder=builder,
    ).run(summary_date=TARGET, orchestrator=object())

    assert result.summary_sent is True
    assert sent == ["27"]


def test_sender_exception_is_logged_and_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(
        daily_sync_module.log_utils,
        "error",
        lambda message: errors.append(message),
    )

    def _raise(message: str) -> bool:
        raise OSError("telegram offline")

    workflow = DailySyncWorkflow(
        daily_sync_service=_SyncService(),
        send_message=_raise,
        summary_builder=_SummaryBuilder(),
    )
    result = workflow.run(summary_date=TARGET, orchestrator=object())

    assert result.summary_sent is False
    assert errors == ["Failed to send daily summary for 2026-08-23: telegram offline"]
