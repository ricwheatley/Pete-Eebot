from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from tests import config_stub  # noqa: F401 - ensure stub settings loaded
from pete_e.application.orchestrator import Orchestrator
from pete_e.infrastructure.telegram_client import TelegramClient
from tests.di_utils import build_stub_container


class _SummaryDal:
    def __init__(self, overview_rows: list[dict[str, object]]):
        self.overview_rows = overview_rows
        self.overview_requests: list[date] = []
        """Initialize this object."""

    def get_metrics_overview(self, target_date: date):
        self.overview_requests.append(target_date)
        if not self.overview_rows:
            return ["metric_name"], []

        columns = list(self.overview_rows[0].keys())
        rows = [tuple(row.get(col) for col in columns) for row in self.overview_rows]
        return columns, rows
        """Perform get metrics overview."""

    def close(self):  # pragma: no cover - compatibility
        pass
        """Perform close."""

    def get_historical_data(self, start_date: date, end_date: date):  # pragma: no cover - used in tests
        return []
        """Perform get historical data."""
    """Represent SummaryDal."""


class _TrainerDal(_SummaryDal):
    def __init__(self, overview_rows: list[dict[str, object]], *, plan_rows):
        super().__init__(overview_rows)
        self.plan_rows = plan_rows
        self.history_requests: list[tuple[date, date]] = []
        """Initialize this object."""

    def get_historical_data(self, start_date: date, end_date: date):
        self.history_requests.append((start_date, end_date))
        base = end_date - timedelta(days=1)
        return [
            {"date": base - timedelta(days=1), "weight_kg": 81.0, "steps": 9000},
            {"date": base, "weight_kg": 80.4, "steps": 12000},
        ]
        """Perform get historical data."""

    def get_plan_for_day(self, target_date: date):
        return ["workout_date", "exercise_name"], [
            (target_date, row) for row in self.plan_rows
        ]
        """Perform get plan for day."""
    """Represent TrainerDal."""


class _RunGuidanceDal(_SummaryDal):
    def __init__(self, overview_rows: list[dict[str, object]], *, action_date: date):
        super().__init__(overview_rows)
        self.action_date = action_date
        """Initialize this object."""

    def get_historical_data(self, start_date: date, end_date: date):
        rows = []
        for idx in range(60, 7, -1):
            rows.append(
                {
                    "date": self.action_date - timedelta(days=idx),
                    "hr_resting": 50.0,
                    "sleep_total_minutes": 420.0,
                    "hrv_sdnn_ms": 60.0,
                }
            )
        for idx in range(7, 0, -1):
            rows.append(
                {
                    "date": self.action_date - timedelta(days=idx),
                    "hr_resting": 54.0,
                    "sleep_total_minutes": 400.0,
                    "hrv_sdnn_ms": 56.0,
                }
            )
        return [row for row in rows if start_date <= row["date"] <= end_date]
        """Perform get historical data."""

    def get_recent_running_workouts(self, *, days: int, end_date: date):
        return [
            {"workout_date": end_date - timedelta(days=idx), "total_distance_km": distance}
            for idx, distance in enumerate([5.0, 4.0, 3.0])
        ]
        """Perform get recent running workouts."""

    def get_plan_for_day(self, target_date: date):
        return ["workout_date", "exercise_name"], [(target_date, "Quality run")]
        """Perform get plan for day."""
    """Represent RunGuidanceDal."""


class _NarrativeBuilder:
    def __init__(self):
        self.calls: list[dict[str, object]] = []
        """Initialize this object."""

    def build_daily_narrative(self, metrics: dict[str, object]) -> str:
        self.calls.append(metrics)
        return "rendered-narrative"
        """Perform build daily narrative."""
    """Represent NarrativeBuilder."""


class _StubTelegram(TelegramClient):
    def __init__(self):
        self.messages: list[str] = []
        """Initialize this object."""

    def send_message(self, message: str, *, chat_id: str | None = None) -> bool:  # type: ignore[override]
        self.messages.append(message)
        return True
        """Perform send message."""
    """Represent StubTelegram."""


def _orchestrator_for(
    dal,
    *,
    narrative_builder: _NarrativeBuilder | None = None,
    telegram_client: TelegramClient | None = None,
):
    container = build_stub_container(
        dal=dal,
        wger_client=SimpleNamespace(),
        plan_service=SimpleNamespace(create_next_plan_for_cycle=lambda start_date: 1),
        export_service=SimpleNamespace(export_plan_week=lambda **_: {}),
        extra_overrides={TelegramClient: lambda _c: telegram_client or _StubTelegram()},
    )
    return Orchestrator(
        container=container,
        narrative_builder=narrative_builder,
    )
    """Perform orchestrator for."""


def test_get_daily_summary_uses_builder():
    overview_rows = [
        {
            "metric_name": "weight",
            "yesterday_value": 82.0,
            "day_before_value": 81.7,
        }
    ]
    dal = _SummaryDal(overview_rows)
    builder = _NarrativeBuilder()

    orch = _orchestrator_for(dal, narrative_builder=builder)

    result = orch.get_daily_summary(target_date=date(2024, 5, 2))

    assert result == "rendered-narrative"
    assert dal.overview_requests == [date(2024, 5, 2)]
    assert builder.calls and "metrics" in builder.calls[0]
    """Perform test get daily summary uses builder."""


def test_get_daily_summary_appends_running_backoff_guidance():
    action_date = date(2024, 6, 10)
    overview_rows = [{"metric_name": "weight", "yesterday_value": 82.0}]
    dal = _RunGuidanceDal(overview_rows, action_date=action_date)
    builder = _NarrativeBuilder()

    orch = _orchestrator_for(dal, narrative_builder=builder)

    result = orch.get_daily_summary(target_date=action_date)

    assert result.startswith("rendered-narrative")
    assert "Run adjustment for Quality run" in result
    assert "swap today's run" in result
    """Perform test get daily summary appends running backoff guidance."""


@pytest.mark.parametrize(
    "plan_rows, expected_fragment",
    [
        ([], "Aujourd'hui: Repos."),
        (["Bench Press", "Pull-Up"], "Bench Press & Pull-Up"),
    ],
)
def test_build_trainer_message_includes_session(plan_rows, expected_fragment):
    overview_rows = [{"metric_name": "weight", "yesterday_value": 82.0}]
    dal = _TrainerDal(overview_rows, plan_rows=plan_rows)
    telegram = _StubTelegram()

    orch = _orchestrator_for(dal, telegram_client=telegram)

    message = orch.build_trainer_message(message_date=date(2024, 5, 3))

    assert "Bonjour" in message
    assert expected_fragment in message
    """Perform test build trainer message includes session."""


def test_send_telegram_message_uses_client():
    overview_rows = [{"metric_name": "weight", "yesterday_value": 82.0}]
    dal = _SummaryDal(overview_rows)
    telegram = _StubTelegram()

    orch = _orchestrator_for(dal, telegram_client=telegram)

    assert orch.send_telegram_message("Salut") is True
    assert telegram.messages == ["Salut"]
    """Perform test send telegram message uses client."""

