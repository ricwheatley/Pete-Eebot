from datetime import date, datetime, timedelta

import pytest

from pete_e.cli import messenger
from pete_e.domain import body_age, narrative_builder


class StubDal:
    def __init__(self, rows):
        self._rows = rows

    def get_historical_data(self, start_date, end_date):
        return [
            row
            for row in self._rows
            if start_date <= row["date"] <= end_date
        ]


def make_row(day: date, value: float | None):
    return {"date": day, "body_age_years": value}


class StubOrchestrator:
    def __init__(self, daily_summary: str, dal: StubDal):
        self._daily_summary = daily_summary
        self.dal = dal
        self.requested_dates: list[date | None] = []

    def get_daily_summary(self, target_date: date | None = None) -> str:
        self.requested_dates.append(target_date)
        return self._daily_summary


def test_get_body_age_trend_computes_delta():
    target = date(2025, 9, 21)
    dal = StubDal(
        [
            make_row(target - timedelta(days=7), 39.2),
            make_row(target - timedelta(days=1), 38.9),
            make_row(target, 38.6),
        ]
    )

    trend = body_age.get_body_age_trend(dal, target_date=target)

    assert trend.sample_date == target
    assert trend.value == pytest.approx(38.6)
    assert trend.delta == pytest.approx(-0.6)


def test_get_body_age_trend_handles_missing_history():
    target = date(2025, 9, 21)
    dal = StubDal([make_row(target, 38.6)])

    trend = body_age.get_body_age_trend(dal, target_date=target)

    assert trend.value == pytest.approx(38.6)
    assert trend.delta is None


def test_build_daily_summary_appends_body_age_line():
    target = date(2025, 9, 21)
    dal = StubDal(
        [
            make_row(target - timedelta(days=7), 39.2),
            make_row(target, 38.6),
        ]
    )
    orch = StubOrchestrator("2025-09-21\nWeight: 82.0 kg", dal)

    summary = messenger.build_daily_summary(orchestrator=orch, target_date=target)

    assert "Body Age: 38.6y" in summary
    assert "7d delta -0.6y" in summary
    assert orch.requested_dates == [target]


def test_build_daily_summary_shows_na_when_missing():
    target = date(2025, 9, 21)
    dal = StubDal([make_row(target, None)])
    orch = StubOrchestrator("2025-09-21\nWeight: 82.0 kg", dal)

    summary = messenger.build_daily_summary(orchestrator=orch, target_date=target)

    assert "Body Age: n/a" in summary


def test_weekly_narrative_includes_body_age_trend(monkeypatch):
    fake_today = date(2025, 9, 22)

    class _FakeDateTime:
        @classmethod
        def utcnow(cls):
            return datetime.combine(fake_today, datetime.min.time())

    monkeypatch.setattr(narrative_builder, "datetime", _FakeDateTime)
    monkeypatch.setattr(narrative_builder.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(narrative_builder.random, "randint", lambda a, b: a)
    monkeypatch.setattr(narrative_builder, "phrase_for", lambda tags: "Keep it up!")
    monkeypatch.setattr(narrative_builder.narrative_utils.random, "random", lambda: 0.99)

    days: dict[str, dict] = {}
    for offset in range(1, 8):
        day = fake_today - timedelta(days=offset)
        days[day.isoformat()] = {"body": {"body_age_years": 38.5}}
    for offset in range(8, 15):
        day = fake_today - timedelta(days=offset)
        days[day.isoformat()] = {"body": {"body_age_years": 39.1}}

    narrative = narrative_builder.build_weekly_narrative({"days": days})

    assert "Body Age averaged 38.5y this week" in narrative
    assert "down 0.6y from last week" in narrative
