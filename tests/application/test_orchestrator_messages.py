from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from tests import config_stub  # noqa: F401 - ensure stub settings loaded
from pete_e.application.orchestrator import Orchestrator
from pete_e.infrastructure.telegram_client import TelegramClient
from tests.di_utils import build_stub_container


class _SummaryDal:
    def __init__(self, summary_payload: dict[str, object]):
        self.summary_payload = summary_payload
        self.summary_requests: list[date] = []

    def get_daily_summary(self, target_date: date):
        self.summary_requests.append(target_date)
        return self.summary_payload

    def close(self):  # pragma: no cover - compatibility
        pass


class _TrainerDal(_SummaryDal):
    def __init__(self, summary_payload: dict[str, object], *, plan_rows):
        super().__init__(summary_payload)
        self.plan_rows = plan_rows
        self.history_requests: list[tuple[date, date]] = []

    def get_historical_data(self, start_date: date, end_date: date):
        self.history_requests.append((start_date, end_date))
        base = end_date - timedelta(days=1)
        return [
            {"date": base - timedelta(days=1), "weight_kg": 81.0, "steps": 9000},
            {"date": base, "weight_kg": 80.4, "steps": 12000},
        ]

    def get_plan_for_day(self, target_date: date):
        return ["workout_date", "exercise_name"], [
            (target_date, row) for row in self.plan_rows
        ]


class _NarrativeBuilder:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def build_daily_summary(self, summary_data: dict[str, object]) -> str:
        self.calls.append(summary_data)
        return "rendered-summary"


class _StubTelegram(TelegramClient):
    def __init__(self):
        self.messages: list[str] = []

    def send_message(self, message: str, *, chat_id: str | None = None) -> bool:  # type: ignore[override]
        self.messages.append(message)
        return True


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
        telegram_client=telegram_client,
    )


def test_get_daily_summary_uses_builder():
    payload = {"date": date(2024, 5, 3), "weight_kg": 82.0}
    dal = _SummaryDal(payload)
    builder = _NarrativeBuilder()

    orch = _orchestrator_for(dal, narrative_builder=builder)

    result = orch.get_daily_summary(target_date=date(2024, 5, 2))

    assert result == "rendered-summary"
    assert dal.summary_requests == [date(2024, 5, 2)]
    assert builder.calls == [payload]


@pytest.mark.parametrize(
    "plan_rows, expected_fragment",
    [
        ([], "Aujourd'hui: Repos."),
        (["Bench Press", "Pull-Up"], "Bench Press & Pull-Up"),
    ],
)
def test_build_trainer_message_includes_session(plan_rows, expected_fragment):
    payload = {"date": date(2024, 5, 3)}
    dal = _TrainerDal(payload, plan_rows=plan_rows)
    telegram = _StubTelegram()

    orch = _orchestrator_for(dal, telegram_client=telegram)

    message = orch.build_trainer_message(message_date=date(2024, 5, 3))

    assert "Bonjour" in message
    assert expected_fragment in message


def test_send_telegram_message_uses_client():
    payload = {"date": date(2024, 5, 3)}
    dal = _SummaryDal(payload)
    telegram = _StubTelegram()

    orch = _orchestrator_for(dal, telegram_client=telegram)

    assert orch.send_telegram_message("Salut") is True
    assert telegram.messages == ["Salut"]

