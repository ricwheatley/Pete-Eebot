from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import types

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator
from pete_e.config import settings
from pete_e.domain import narrative_builder, phrase_picker




class LedgerStub:
    def __init__(self) -> None:
        self.sent: dict[date, str] = {}

    def was_sent(self, target_date: date) -> bool:
        return target_date in self.sent

    def mark_sent(self, target_date: date, summary: str) -> None:
        self.sent[target_date] = summary


class DayInLifeDal:
    def __init__(self, target_day: date) -> None:
        self.target_day = target_day
        self.saved_withings: list[tuple] = []
        self.saved_wger: list[tuple] = []
        self.summary_requests: list[date] = []
        self.historical_metric_requests: list[int] = []
        self.historical_data_requests: list[tuple[date, date]] = []
        self.body_age_computes: list[tuple[date, date]] = []
        self.refreshed_actual_view = False

        self.summary_payload = {
            "date": target_day,
            "weight_kg": 82.3,
            "body_fat_pct": 18.5,
            "muscle_pct": 41.2,
            "water_pct": 55.8,
            "hr_resting": 54,
            "hrv_sdnn_ms": 96.0,
            "steps": 12_345,
            "calories_active": 723,
            "sleep_asleep_minutes": 430,
            "environment_temp_degc": 18.5,
            "environment_humidity_percent": 45.0,
            "readiness_headline": "Ready to rock",
            "readiness_tip": "Keep the streak alive",
        }

        previous_muscles = [40.0, 40.1, 40.2, 40.1, 40.0, 40.3, 40.2]
        current_muscles = [41.0, 41.1, 41.2, 41.1, 41.3, 41.2, 41.1]
        hrv_series = [90.0, 90.0, 92.0, 92.0, 94.0, 94.0, 96.0]

        history: list[dict] = []
        for offset in range(13, -1, -1):
            day = target_day - timedelta(days=offset)
            entry = {"date": day}
            if offset >= 7:
                entry["muscle_pct"] = previous_muscles[13 - offset]
            else:
                entry["muscle_pct"] = current_muscles[6 - offset]
                entry["hrv_sdnn_ms"] = hrv_series[6 - offset]
            history.append(entry)
        self.metrics_history = history

        body_age_sequence = [39.2, 39.1, 39.05, 39.0, 38.9, 38.8, 38.7, 38.6]
        steps_sequence = [9800, 9900, 10000, 10100, 10200, 10300, 10400, 10500]
        sleep_sequence = [420, 430, 440, 450, 455, 460, 470, 480]

        rows: list[dict] = []
        for index, offset in enumerate(range(7, -1, -1)):
            day = target_day - timedelta(days=offset)
            row = {
                "date": day,
                "body_age_years": body_age_sequence[index],
                "activity": {"steps": steps_sequence[index]},
                "sleep": {"asleep_minutes": sleep_sequence[index]},
                "steps": steps_sequence[index],
                "sleep_asleep_minutes": sleep_sequence[index],
            }
            rows.append(row)
        self.historical_rows = rows

    def save_withings_daily(self, day, weight_kg, body_fat_pct, muscle_pct, water_pct):
        self.saved_withings.append((day, weight_kg, body_fat_pct, muscle_pct, water_pct))

    def save_wger_log(self, day, exercise_id, set_number, reps, weight_kg, rir):
        self.saved_wger.append((day, exercise_id, set_number, reps, weight_kg, rir))

    def refresh_actual_view(self):
        self.refreshed_actual_view = True

    def compute_body_age_for_date(self, target_day: date, birth_date: date) -> None:
        self.body_age_computes.append((target_day, birth_date))

    def get_daily_summary(self, target_date: date):
        self.summary_requests.append(target_date)
        if target_date != self.target_day:
            return None
        return dict(self.summary_payload)

    def get_historical_metrics(self, days: int):
        self.historical_metric_requests.append(days)
        return [dict(row) for row in self.metrics_history]

    def get_historical_data(self, start_date: date, end_date: date):
        self.historical_data_requests.append((start_date, end_date))
        return [
            dict(row)
            for row in self.historical_rows
            if start_date <= row["date"] <= end_date
        ]

    def load_lift_log(self, *, end_date: date | None = None):
        return {}


def test_day_in_life_end_to_end(monkeypatch):
    fixed_today = date(2024, 8, 17)
    target_day = fixed_today - timedelta(days=1)
    real_datetime = datetime

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed_today

    monkeypatch.setattr(orchestrator_module, "date", _FixedDate)

    class _FixedDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            base = real_datetime.combine(fixed_today, real_datetime.min.time())
            if tz is not None:
                return base.replace(tzinfo=tz)
            return base

    monkeypatch.setattr(orchestrator_module, "datetime", _FixedDateTime)

    withings_snapshot = {
        "weight": 82.3,
        "fat_percent": 18.5,
        "muscle_percent": 41.2,
        "water_percent": 55.8,
    }
    wger_entries = [
        {"exercise_id": 101, "reps": 8, "weight": 60.0, "rir": 1},
        {"exercise_id": 101, "reps": 8, "weight": 62.5, "rir": 0},
    ]

    class DummyWithingsClient:
        def get_summary(self, days_back):
            assert days_back >= 1
            return dict(withings_snapshot)

    class DummyWgerClient:
        def get_logs_by_date(self, days):
            assert days == 1
            return {target_day.isoformat(): [dict(entry) for entry in wger_entries]}

    monkeypatch.setattr(orchestrator_module, "WithingsClient", DummyWithingsClient)
    monkeypatch.setattr(orchestrator_module, "WgerClient", DummyWgerClient)

    apple_reports: list = []

    def fake_apple_ingest():
        report = types.SimpleNamespace(sources=["daily.json"], workouts=1, daily_points=5)
        apple_reports.append(report)
        return report

    monkeypatch.setattr(orchestrator_module, "run_apple_health_ingest", fake_apple_ingest)
    monkeypatch.setattr(
        orchestrator_module,
        "get_last_successful_import_timestamp",
        lambda: datetime.combine(fixed_today, datetime.min.time(), tzinfo=timezone.utc),
    )

    alerts: list[str] = []
    monkeypatch.setattr(
        orchestrator_module.telegram_sender,
        "send_alert",
        lambda message: alerts.append(message) or True,
    )

    def fake_phrase(*args, **kwargs):
        return ""

    monkeypatch.setattr(phrase_picker, "random_phrase", fake_phrase)
    monkeypatch.setattr(narrative_builder, "phrase_for", fake_phrase)
    monkeypatch.setattr(narrative_builder.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(narrative_builder.random, "random", lambda: 0.0)
    monkeypatch.setattr(narrative_builder.random, "randint", lambda a, b: a)

    monkeypatch.setattr(Orchestrator, "dispatch_nudges", lambda self, reference_date=None: [])

    sent_messages: list[str] = []

    def fake_send(self, message: str) -> bool:
        sent_messages.append(message)
        return True

    monkeypatch.setattr(Orchestrator, "send_telegram_message", fake_send, raising=False)

    ledger = LedgerStub()
    dal = DayInLifeDal(target_day)
    orch = Orchestrator(dal=dal, summary_dispatch_ledger=ledger)

    result = orch.run_end_to_end_day(days=1, summary_date=target_day)

    assert result.ingest_success is True
    assert result.failed_sources == []
    assert result.source_statuses == {
        "AppleDropbox": "ok",
        "Withings": "ok",
        "Wger": "ok",
        "BodyAge": "ok",
    }
    assert result.summary_target == target_day
    assert result.summary_sent is True

    assert alerts == [] or alerts == ["daily_summary may be stale."]
    assert len(apple_reports) == 1
    assert dal.saved_withings == [
        (target_day, 82.3, 18.5, 41.2, 55.8)
    ]
    assert dal.saved_wger == [
        (target_day, 101, 1, 8, 60.0, 1),
        (target_day, 101, 2, 8, 62.5, 0),
    ]
    assert dal.refreshed_actual_view is True
    assert dal.body_age_computes == [(target_day, settings.USER_DATE_OF_BIRTH)]
    assert dal.summary_requests == [target_day]

    expected_summary = "\n".join(
        [
            "Yo Ric! Coach Pete sliding into your DMs 💥",
            "",
            "*Friday 16 Aug: Daily Flex*",
            "- Weight: 82.3 kg",
            "- Body fat: 18.5%",
            "- Muscle: 41.2%",
            "- Hydration: 55.8%",
            "- Resting HR: 54 bpm",
            "- HRV: 96 ms",
            "- Steps: 12,345 struts",
            "- Active burn: 723 kcal",
            "- Sleep: 7h 10m logged",
            "- Environment: 18.5 degC and 45% humidity reported for the workout.",
            "Coach's call: Ready to rock - Keep the streak alive.",
            "Consistency is queen, volume is king!",
            "Body Age: 38.6y (7d delta -0.6y)",
            "Muscle trend: 41.1% avg this week (up 1.0% vs prior).",
            "HRV: 96 ms ↗ (7d avg 92 ms)",
            "Trend check: Steps trend: need more data logged (only 8 days in last 30d). Sleep trend: need more data logged (only 8 days in last 30d).",
        ]
    )

    assert sent_messages == [expected_summary]
    assert ledger.sent[target_day] == expected_summary
