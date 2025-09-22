from datetime import date, datetime, timedelta

import pytest

from pete_e.domain import narrative_builder
from pete_e.cli import messenger


class _DeterministicRandom:
    def choice(self, seq):
        if not seq:
            raise ValueError('choice sequence was empty')
        return seq[0]

    def randint(self, a, b):
        return a

    def random(self):
        return 0.0


def _build_day_series(as_of: date, days: int) -> dict[str, dict]:
    series: dict[str, dict] = {}
    for offset in range(1, days + 1):
        day = as_of - timedelta(days=offset)
        # recent days (smaller offset) trend higher than older days
        trend_factor = days - offset + 1
        steps = 6000 + (trend_factor * 85)
        sleep_minutes = int((6.3 + trend_factor * 0.015) * 60)
        series[day.isoformat()] = {
            'activity': {'steps': steps},
            'sleep': {'asleep_minutes': sleep_minutes},
        }
    return series


def _series_to_samples(series: dict[str, dict]) -> list[tuple[date, dict]]:
    samples = []
    for iso_day, payload in series.items():
        samples.append((date.fromisoformat(iso_day), payload))
    samples.sort(key=lambda item: item[0])
    return samples


def test_compute_trend_lines_produces_steps_and_sleep(monkeypatch):
    fake_today = date(2025, 9, 22)
    days = _build_day_series(fake_today, 90)
    samples = _series_to_samples(days)

    lines = narrative_builder.compute_trend_lines(samples, as_of=fake_today - timedelta(days=1))

    assert len(lines) >= 2
    assert any('Steps trend' in line and '30d' in line and '60d' in line for line in lines)
    assert any('Sleep trend' in line and '30d' in line and '60d' in line for line in lines)


def test_compute_trend_lines_acknowledges_sparse_data(monkeypatch):
    fake_today = date(2025, 9, 22)
    days = _build_day_series(fake_today, 12)
    samples = _series_to_samples(days)

    lines = narrative_builder.compute_trend_lines(samples, as_of=fake_today - timedelta(days=1))

    steps_line = next(line for line in lines if 'Steps trend' in line)
    assert 'more data' in steps_line


def test_weekly_narrative_embeds_trend_lines(monkeypatch):
    fake_today = date(2025, 9, 22)

    class _FixedDateTime:
        @classmethod
        def utcnow(cls):
            return datetime.combine(fake_today, datetime.min.time())

    deterministic = _DeterministicRandom()
    monkeypatch.setattr(narrative_builder, 'datetime', _FixedDateTime)
    monkeypatch.setattr(narrative_builder, 'random', deterministic)
    monkeypatch.setattr(narrative_builder.narrative_utils.random, 'random', lambda: 0.99)
    monkeypatch.setattr(narrative_builder.narrative_utils.random, 'choice', lambda seq: seq[0])
    monkeypatch.setattr(narrative_builder, 'phrase_for', lambda *_, **__: 'Keep charging ahead!')

    days = _build_day_series(fake_today, 90)
    narrative = narrative_builder.build_weekly_narrative({'days': days})

    assert 'Steps trend' in narrative
    assert 'Sleep trend' in narrative
    assert '60d' in narrative


def test_daily_summary_appends_trend_paragraph(monkeypatch):
    target = date(2025, 9, 21)
    fake_today = target + timedelta(days=1)

    class StubDal:
        def __init__(self):
            self.rows = []
            full_series = _build_day_series(fake_today, 90)
            for iso_day, payload in full_series.items():
                day = date.fromisoformat(iso_day)
                self.rows.append({
                    'date': day,
                    'steps': payload['activity']['steps'],
                    'sleep_asleep_minutes': payload['sleep']['asleep_minutes'],
                })
            self.rows.sort(key=lambda item: item['date'])

        def get_historical_data(self, start_date, end_date):
            return [row for row in self.rows if start_date <= row['date'] <= end_date]

    class StubOrchestrator:
        def __init__(self):
            self.dal = StubDal()
            self.queries = []

        def get_daily_summary(self, target_date=None):
            self.queries.append(target_date)
            return 'Base summary'

    monkeypatch.setattr(messenger.body_age, 'get_body_age_trend', lambda *_, **__: None)

    orch = StubOrchestrator()
    summary = messenger.build_daily_summary(orchestrator=orch, target_date=target)

    assert 'Base summary' in summary
    assert 'Trend check' in summary
    assert 'Steps trend' in summary
    assert 'Sleep trend' in summary
    assert orch.queries == [target]
