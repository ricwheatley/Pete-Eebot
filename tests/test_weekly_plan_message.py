from datetime import date as real_date

from typer.testing import CliRunner

from pete_e.cli import messenger
from pete_e.domain import narrative_builder


class StubDal:
    def __init__(self, start_date: real_date, weeks: int = 4) -> None:
        self._plan = {
            "id": 42,
            "start_date": start_date,
            "weeks": weeks,
        }
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

    def get_plan_week(self, plan_id: int, week_number: int):
        assert plan_id == self._plan["id"]
        assert week_number == 1
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
    assert "Yo Ric! Coach Pete's weekly huddle incoming" in output
    assert "*Week 1 Game Plan · 2024-09-02 → 2024-09-08*" in output
    assert "- Monday: Squat (3 x 5 · RIR 2) | Bench Press (3 x 8 · RIR 1)" in output
    assert "- Rest windows: Tuesday, Thursday, Friday, Saturday, Sunday - keep them mobile." in output
    assert "Coach's call: Week 1 is all about momentum - lock it in." in output
    assert "Remember to hydrate." in output
    assert orch.sent_message is None


def test_weekly_plan_cli_send_uses_formatted_overview(monkeypatch):
    orch = _setup(monkeypatch)
    expected = messenger.build_weekly_plan_overview(orchestrator=orch, target_date=FixedDate.today())

    result = runner.invoke(messenger.app, ["message", "--plan", "--send"], catch_exceptions=False)

    assert result.exit_code == 0
    assert orch.sent_message == expected
