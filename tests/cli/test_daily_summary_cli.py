"""Real Typer/Click contracts for daily-summary commands."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from pete_e.cli import messenger


pytestmark = pytest.mark.contract


def _invoke(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str], orchestrator: object
):
    monkeypatch.setattr(messenger, "_build_orchestrator", lambda: orchestrator)
    return CliRunner().invoke(messenger.app, arguments)


def test_message_summary_prints_exact_header_text_and_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs: list[tuple[str, str]] = []
    orchestrator = SimpleNamespace(
        build_daily_summary_message=lambda target_date=None: "Daily report"
    )
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level: logs.append((message, level)),
    )

    result = _invoke(monkeypatch, ["message", "--summary"], orchestrator)

    assert result.exit_code == 0
    assert result.stdout == "--- Daily Summary ---\nDaily report\n"
    assert result.stderr == ""
    assert logs == [("Generating daily summary...", "INFO")]


def test_message_summary_send_uses_generated_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []
    orchestrator = SimpleNamespace(
        build_daily_summary_message=lambda target_date=None: "Daily report"
    )
    monkeypatch.setattr(
        messenger,
        "send_daily_summary",
        lambda *, orchestrator, summary_text: sent.append(summary_text) or summary_text,
    )

    result = _invoke(
        monkeypatch,
        ["message", "--summary", "--send"],
        orchestrator,
    )

    assert result.exit_code == 0
    assert sent == ["Daily report"]


def test_message_without_selector_exits_one_without_building(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        messenger,
        "_build_orchestrator",
        lambda: (_ for _ in ()).throw(AssertionError("must not build")),
    )
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level: logs.append((message, level)),
    )

    result = CliRunner().invoke(messenger.app, ["message"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == ""
    assert logs == [
        (
            "Please specify a message type to generate: --summary, --trainer, or --plan",
            "WARN",
        )
    ]


def test_message_multiple_flags_are_processed_independently_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = object()
    monkeypatch.setattr(messenger, "build_daily_summary", lambda **kwargs: "summary")
    monkeypatch.setattr(messenger, "build_trainer_summary", lambda **kwargs: "trainer")
    monkeypatch.setattr(
        messenger,
        "build_weekly_plan_overview",
        lambda **kwargs: "plan",
    )

    result = _invoke(
        monkeypatch,
        ["message", "--summary", "--trainer", "--plan"],
        orchestrator,
    )

    assert result.exit_code == 0
    assert result.stdout == (
        "--- Daily Summary ---\nsummary\n"
        "--- Trainer Summary ---\ntrainer\n"
        "--- Weekly Plan ---\nplan\n"
    )


def test_message_summary_send_failure_logs_and_exits_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr(messenger, "build_daily_summary", lambda **kwargs: "summary")
    monkeypatch.setattr(
        messenger,
        "send_daily_summary",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("send failed")),
    )
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level: logs.append((message, level)),
    )

    result = _invoke(
        monkeypatch,
        ["message", "--summary", "--send"],
        object(),
    )

    assert result.exit_code == 1
    assert result.stdout == "--- Daily Summary ---\nsummary\n"
    assert logs[-1] == (
        "Failed to send daily summary via Telegram: send failed",
        "ERROR",
    )


def test_morning_report_parses_date_and_prints_heading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[date | None] = []
    orchestrator = object()
    monkeypatch.setattr(
        messenger,
        "build_daily_summary",
        lambda *, orchestrator, target_date: requested.append(target_date)
        or "Morning text",
    )

    result = _invoke(
        monkeypatch,
        ["morning-report", "--date", "2026-08-23"],
        orchestrator,
    )

    assert result.exit_code == 0
    assert result.stdout == "--- Morning Report ---\nMorning text\n"
    assert requested == [date(2026, 8, 23)]


def test_morning_report_invalid_date_uses_stderr_and_exits_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        messenger,
        "build_daily_summary",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not build")),
    )

    result = _invoke(
        monkeypatch,
        ["morning-report", "--date", "23-08-2026"],
        object(),
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Invalid date supplied to --date. Use YYYY-MM-DD.\n"


@pytest.mark.parametrize("report", ["", " \n"])
def test_morning_report_blank_message_has_exact_zero_exit_fallback(
    monkeypatch: pytest.MonkeyPatch,
    report: str,
) -> None:
    monkeypatch.setattr(messenger, "build_daily_summary", lambda **kwargs: report)

    result = _invoke(monkeypatch, ["morning-report"], object())

    assert result.exit_code == 0
    assert (
        result.stdout == "No morning report is available yet. Give the sync a minute.\n"
    )
    assert result.stderr == ""


def test_morning_report_send_uses_rendered_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(messenger, "build_daily_summary", lambda **kwargs: "report")
    monkeypatch.setattr(
        messenger,
        "send_daily_summary",
        lambda *, orchestrator, summary_text: sent.append(summary_text) or summary_text,
    )

    result = _invoke(monkeypatch, ["morning-report", "--send"], object())

    assert result.exit_code == 0
    assert sent == ["report"]


def test_morning_report_send_failure_logs_and_exits_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr(messenger, "build_daily_summary", lambda **kwargs: "report")
    monkeypatch.setattr(
        messenger,
        "send_daily_summary",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("send failed")),
    )
    monkeypatch.setattr(
        messenger.log_utils,
        "log_message",
        lambda message, level: logs.append((message, level)),
    )

    result = _invoke(monkeypatch, ["morning-report", "--send"], object())

    assert result.exit_code == 1
    assert result.stdout == "--- Morning Report ---\nreport\n"
    assert logs == [
        ("Failed to send morning report via Telegram: send failed", "ERROR")
    ]
