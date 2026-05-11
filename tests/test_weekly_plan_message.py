from datetime import date as real_date

from typer.testing import CliRunner

import tests.config_stub  # noqa: F401

from pete_e.cli import messenger
from pete_e.domain import schedule_rules
from pete_e.domain import narrative_builder


class StubDal:
    def __init__(self, start_date: real_date, weeks: int = 4, expected_week_number: int = 1) -> None:
        self._plan = {
            "id": 42,
            "start_date": start_date,
            "weeks": weeks,
        }
        self.expected_week_number = expected_week_number
        self._week_rows = [
            {
                "day_of_week": 1,
                "exercise_name": "Squat",
                "sets": 3,
                "reps": 5,
                "rir": 2,
            },
            {
                "day_of_week": 1,
                "exercise_name": "Bench Press",
                "sets": 3,
                "reps": 8,
                "rir": 1,
            },
            {
                "day_of_week": 3,
                "exercise_name": "Tempo Run",
            },
        ]

    def get_active_plan(self):
        return self._plan

    def get_plan_week_rows(self, plan_id: int, week_number: int):
        assert plan_id == self._plan["id"]
        assert week_number == self.expected_week_number
        return list(self._week_rows)


class StubOrchestrator:
    def __init__(self, dal: StubDal) -> None:
        self.dal = dal
        self.sent_message: str | None = None

    def send_telegram_message(self, message: str) -> bool:
        self.sent_message = message
        return True


class FixedDate(real_date):
    @classmethod
    def today(cls) -> "FixedDate":
        return cls(2024, 9, 4)


class _DeterministicRandom:
    def choice(self, seq):
        if not seq:
            raise ValueError("choice sequence was empty")
        return seq[0]

    def randint(self, a, b):
        return a

    def random(self):
        return 0.0


runner = CliRunner()


def _setup(monkeypatch):
    start = FixedDate(2024, 9, 2)
    dal = StubDal(start)
    orch = StubOrchestrator(dal)
    deterministic = _DeterministicRandom()
    monkeypatch.setattr(narrative_builder, "random", deterministic)
    monkeypatch.setattr(narrative_builder, "phrase_for", lambda **_: "Remember to hydrate.")
    monkeypatch.setattr(messenger, "_build_orchestrator", lambda: orch)
    monkeypatch.setattr(messenger, "date", FixedDate)
    return orch


def test_weekly_plan_cli_formats_overview(monkeypatch):
    orch = _setup(monkeypatch)
    expected = messenger.build_weekly_plan_overview(orchestrator=orch, target_date=FixedDate.today())

    result = runner.invoke(messenger.app, ["message", "--plan"], catch_exceptions=False)

    assert result.exit_code == 0
    output = result.stdout.strip()
    assert expected in output
    assert "Cycle week: 1" in output
    assert "Monday:" in output
    assert "Squat (3 x 5 · RIR 2)" in output
    assert "Bench Press (3 x 8 · RIR 1)" in output
    assert orch.sent_message is None


def test_weekly_plan_cli_send_uses_formatted_overview(monkeypatch):
    orch = _setup(monkeypatch)
    expected = messenger.build_weekly_plan_overview(orchestrator=orch, target_date=FixedDate.today())

    result = runner.invoke(messenger.app, ["message", "--plan", "--send"], catch_exceptions=False)

    assert result.exit_code == 0
    assert orch.sent_message == expected


def test_weekly_plan_overview_targets_next_week_when_run_on_sunday(monkeypatch):
    class SundayDate(real_date):
        @classmethod
        def today(cls) -> "SundayDate":
            return cls(2024, 9, 8)

    plan_start = SundayDate(2024, 9, 2)
    dal = StubDal(plan_start, expected_week_number=2)
    orch = StubOrchestrator(dal)
    deterministic = _DeterministicRandom()
    monkeypatch.setattr(narrative_builder, "random", deterministic)
    monkeypatch.setattr(narrative_builder, "phrase_for", lambda **_: "Remember to hydrate.")
    monkeypatch.setattr(messenger, "date", SundayDate)

    message = messenger.build_weekly_plan_overview(orchestrator=orch)

    assert "Cycle week: 2" in message


def test_weekly_plan_formats_interval_treadmill_steps():
    rows = [
        {
            "day_of_week": 1,
            "comment": "Quality run",
            "details": {
                "session_type": "intervals",
                "steps": [
                    {"kind": "warmup", "duration_minutes": 5, "speed_kph": 8.5},
                    {
                        "kind": "repeat",
                        "repeats": 5,
                        "steps": [
                            {"kind": "work", "duration_minutes": 3, "speed_kph": 11.5},
                            {"kind": "recovery", "duration_minutes": 2, "speed_kph": 8.5},
                        ],
                    },
                    {"kind": "cooldown", "duration_minutes": 5, "speed_kph": 8.5},
                ],
            },
        }
    ]

    message = narrative_builder.build_weekly_plan_summary(rows, week_number=1, week_start=real_date(2024, 9, 2))
    assert "Warmup 5 min @ 8.5 km/h; 5 × (3 min @ 11.5 km/h, 2 min @ 8.5 km/h); Cooldown 5 min @ 8.5 km/h" in message


def test_weekly_plan_formats_tempo_treadmill_steps():
    rows = [
        {
            "day_of_week": 1,
            "comment": "Quality run",
            "details": {
                "session_type": "tempo",
                "steps": [
                    {"kind": "warmup", "duration_minutes": 5, "speed_kph": 8.5},
                    {"kind": "steady", "duration_minutes": 20, "speed_kph": 10.5},
                    {"kind": "cooldown", "duration_minutes": 5, "speed_kph": 8.5},
                ],
            },
        }
    ]

    message = narrative_builder.build_weekly_plan_summary(rows, week_number=1, week_start=real_date(2024, 9, 2))
    assert "Warmup 5 min @ 8.5 km/h; 20 min @ 10.5 km/h; Cooldown 5 min @ 8.5 km/h" in message


def test_weekly_plan_legacy_rows_render_without_treadmill_details():
    rows = [{"day_of_week": 1, "exercise_name": "Bench Press", "sets": 5, "reps": 5, "rir": 2}]
    message = narrative_builder.build_weekly_plan_summary(rows, week_number=1, week_start=real_date(2024, 9, 2))
    assert "Monday:" in message
    assert "Bench Press (5 x 5 · RIR 2)" in message


def test_weekly_plan_formats_limber_11_and_orders_run_weights_stretch():
    rows = [
        {
            "day_of_week": 1,
            "exercise_name": "Bench Press",
            "sets": 5,
            "reps": 5,
            "rir": 2,
        },
        {
            "day_of_week": 1,
            "comment": "Limber 11",
            "details": {
                "session_type": schedule_rules.STRETCH_SESSION_TYPE,
                "display_name": "Limber 11",
                "steps": [
                    {"name": "Seated Piriformis Stretch", "is_isometric": True},
                    {
                        "name": "Rear-foot-elevated Hip Flexor Stretch",
                        "is_isometric": False,
                        "includes_isometric_hold": True,
                        "hold_seconds": 3,
                    },
                ],
            },
        },
        {
            "day_of_week": 1,
            "comment": "Quality run",
            "is_cardio": True,
            "details": {
                "session_type": "tempo",
                "steps": [
                    {"kind": "warmup", "duration_minutes": 5, "speed_kph": 8.5},
                    {"kind": "steady", "duration_minutes": 20, "speed_kph": 10.5},
                    {"kind": "cooldown", "duration_minutes": 5, "speed_kph": 8.5},
                ],
            },
        },
    ]

    message = narrative_builder.build_weekly_plan_summary(rows, week_number=1, week_start=real_date(2024, 9, 2))
    lines = message.splitlines()
    monday_idx = lines.index("Monday:")
    tuesday_idx = len(lines)
    monday_entries = lines[monday_idx + 1:tuesday_idx]

    joined = "\n".join(monday_entries)
    assert joined.index("Quality run") < joined.index("Bench Press") < joined.index("Limber 11")
    assert "Seated Piriformis Stretch [isometric]" in joined
    assert "Rear-foot-elevated Hip Flexor Stretch [dynamic + 3s hold]" in joined
