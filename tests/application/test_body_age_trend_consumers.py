"""Compatibility contracts for the two body-age summary consumers."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from pete_e.application.orchestrator import Orchestrator
from pete_e.cli import messenger
from pete_e.domain import body_age
from tests.di_utils import build_stub_container


TARGET = date(2026, 8, 23)
EXPECTED = body_age.BodyAgeTrend(sample_date=TARGET, value=38.6, delta=-0.6)


class _BodyAgeDal:
    def get_historical_data(self, start_date: date, end_date: date):
        return [
            {"date": start_date, "body_age_years": 39.2},
            {"date": end_date, "body_age_years": 38.6},
        ]

    def get_metrics_overview(self, _target_date: date):
        return ["metric_name", "yesterday_value"], [("weight", 82.0)]

    def get_nutrition_daily_summary(self, _target_date: date):
        return {"meals_logged": 0}

    def close(self) -> None:
        return None


class _CliOrchestrator:
    def __init__(self, dal: _BodyAgeDal) -> None:
        self.dal = dal

    def get_daily_summary(self, target_date: date | None = None) -> str:
        return f"Base summary for {target_date}"


class _NarrativeBuilder:
    def build_daily_narrative(self, _metrics: dict[str, object]) -> str:
        return "rendered-narrative"


def _application_orchestrator(dal: _BodyAgeDal) -> Orchestrator:
    container = build_stub_container(
        dal=dal,
        wger_client=SimpleNamespace(),
        plan_service=SimpleNamespace(create_next_plan_for_cycle=lambda start_date: 1),
        export_service=SimpleNamespace(export_plan_week=lambda **_: {}),
    )
    return Orchestrator(container=container, narrative_builder=_NarrativeBuilder())


def test_cli_summary_receives_unchanged_body_age_trend() -> None:
    dal = _BodyAgeDal()

    assert body_age.get_body_age_trend(dal, target_date=TARGET) == EXPECTED
    summary = messenger.build_daily_summary(
        orchestrator=_CliOrchestrator(dal),
        target_date=TARGET,
    )
    assert "Body Age: 38.6y (7d delta -0.6y)" in summary


def test_application_summary_receives_unchanged_body_age_trend() -> None:
    dal = _BodyAgeDal()
    orchestrator = _application_orchestrator(dal)

    assert body_age.get_body_age_trend(dal, target_date=TARGET) == EXPECTED
    assert orchestrator._format_body_age_line(TARGET) == (
        "Body Age: 38.6y (7d delta -0.6y)"
    )
    assert "Body Age: 38.6y (7d delta -0.6y)" in orchestrator.get_daily_summary(
        target_date=TARGET
    )
