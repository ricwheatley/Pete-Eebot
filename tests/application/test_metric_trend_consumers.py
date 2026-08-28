"""Compatibility checks for the three production metric-trend consumers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from pete_e.application.orchestrator import Orchestrator
from pete_e.cli import messenger
from pete_e.domain import narrative_builder
from tests.di_utils import build_stub_container


TARGET = date(2026, 8, 23)
STEPS_LINE = (
    "Steps trend: 10,000 steps/day "
    "(steady vs 30d avg 10,000 steps/day; 60d base 10,000 steps/day)."
)
SLEEP_LINE = (
    "Sleep trend: 7.0 h/night " "(steady vs 30d avg 7.0 h/night; 60d base 7.0 h/night)."
)
TREND_PARAGRAPH = f"Trend check: {STEPS_LINE} {SLEEP_LINE}"


def _history_rows() -> list[dict[str, object]]:
    return [
        {
            "date": TARGET - timedelta(days=offset),
            "steps": 10_000,
            "sleep_asleep_minutes": 420,
        }
        for offset in range(51)
    ]


class _TrendDal:
    def get_historical_data(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        return [
            row
            for row in _history_rows()
            if start_date <= row["date"] <= end_date  # type: ignore[operator]
        ]

    def get_metrics_overview(self, _target_date: date):
        return ["metric_name", "yesterday_value"], [("weight", 82.0)]

    def get_nutrition_daily_summary(self, _target_date: date):
        return {"meals_logged": 0}

    def close(self) -> None:
        return None


class _CliOrchestrator:
    def __init__(self, dal: _TrendDal) -> None:
        self.dal = dal

    def get_daily_summary(self, target_date: date | None = None) -> str:
        return f"Base summary for {target_date}"


class _NarrativeBuilder:
    def build_daily_narrative(self, _metrics: dict[str, object]) -> str:
        return "Base application summary"


def _application_orchestrator(dal: _TrendDal) -> Orchestrator:
    container = build_stub_container(
        dal=dal,
        wger_client=SimpleNamespace(),
        plan_service=SimpleNamespace(create_next_plan_for_cycle=lambda start_date: 1),
        export_service=SimpleNamespace(export_plan_week=lambda **_: {}),
    )
    return Orchestrator(container=container, narrative_builder=_NarrativeBuilder())


def test_cli_daily_summary_keeps_exact_trend_paragraph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(messenger.body_age, "get_body_age_trend", lambda *_, **__: None)

    summary = messenger.build_daily_summary(
        orchestrator=_CliOrchestrator(_TrendDal()),
        target_date=TARGET,
    )

    assert summary == f"Base summary for {TARGET}\n{TREND_PARAGRAPH}"


def test_application_orchestrator_keeps_exact_trend_paragraph() -> None:
    summary = _application_orchestrator(_TrendDal()).get_daily_summary(
        target_date=TARGET
    )

    assert summary == f"Base application summary\n{TREND_PARAGRAPH}"


def test_weekly_narrative_keeps_metric_order_and_exact_trend_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FixedDateTime:
        @classmethod
        def utcnow(cls) -> datetime:
            return datetime.combine(TARGET + timedelta(days=1), datetime.min.time())

    monkeypatch.setattr(narrative_builder, "datetime", _FixedDateTime)
    monkeypatch.setattr(narrative_builder.random, "choice", lambda values: values[0])
    monkeypatch.setattr(narrative_builder.random, "randint", lambda start, end: start)
    monkeypatch.setattr(
        narrative_builder, "phrase_for", lambda *args, **kwargs: "Keep going!"
    )
    monkeypatch.setattr(
        narrative_builder.narrative_utils.random, "random", lambda: 0.99
    )
    days = {
        row["date"].isoformat(): {
            "activity": {"steps": row["steps"]},
            "sleep": {"asleep_minutes": row["sleep_asleep_minutes"]},
        }
        for row in _history_rows()
    }

    summary = narrative_builder.build_weekly_narrative({"days": days})

    assert STEPS_LINE in summary
    assert SLEEP_LINE in summary
    assert summary.index(STEPS_LINE) < summary.index(SLEEP_LINE)
