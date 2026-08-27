from datetime import date as real_date

import pytest
from typer.testing import CliRunner

from pete_e.cli import messenger
from pete_e.domain import schedule_rules
from pete_e.domain import narrative_builder


class StubDal:
    def __init__(
        self, start_date: real_date, weeks: int = 4, expected_week_number: int = 1
    ) -> None:
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


class RecordingVoice:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = []

    def compose(self, request, *, fallback_message: str) -> str:
        self.calls.append({"request": request, "fallback": fallback_message})
        return self.response


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
    monkeypatch.setattr(
        narrative_builder, "phrase_for", lambda **_: "Remember to hydrate."
    )
    monkeypatch.setattr(messenger, "_build_orchestrator", lambda: orch)
    monkeypatch.setattr(messenger, "date", FixedDate)
    return orch


def test_weekly_plan_cli_formats_overview(monkeypatch):
    orch = _setup(monkeypatch)
    expected = messenger.build_weekly_plan_overview(
        orchestrator=orch, target_date=FixedDate.today()
    )

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
    expected = messenger.build_weekly_plan_overview(
        orchestrator=orch, target_date=FixedDate.today()
    )

    result = runner.invoke(
        messenger.app, ["message", "--plan", "--send"], catch_exceptions=False
    )

    assert result.exit_code == 0
    assert orch.sent_message == expected


def test_weekly_plan_uses_structured_voice_when_available(monkeypatch):
    orch = _setup(monkeypatch)
    voice = RecordingVoice("Voice-written weekly plan")
    orch.voice_service = voice

    message = messenger.build_weekly_plan_overview(
        orchestrator=orch, target_date=FixedDate.today()
    )

    assert message == "Voice-written weekly plan"
    assert voice.calls
    request = voice.calls[0]["request"]
    assert request.message_type == "weekly_plan"
    assert request.recent_context["plan_week_rows"][0]["exercise_name"] == "Squat"
    assert voice.calls[0]["fallback"].startswith("Cycle week: 1")


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
    monkeypatch.setattr(
        narrative_builder, "phrase_for", lambda **_: "Remember to hydrate."
    )
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
                            {
                                "kind": "recovery",
                                "duration_minutes": 2,
                                "speed_kph": 8.5,
                            },
                        ],
                    },
                    {"kind": "cooldown", "duration_minutes": 5, "speed_kph": 8.5},
                ],
            },
        }
    ]

    message = narrative_builder.build_weekly_plan_summary(
        rows, week_number=1, week_start=real_date(2024, 9, 2)
    )
    assert (
        "Warmup 5 min @ 8.5 km/h; 5 × (3 min @ 11.5 km/h, 2 min @ 8.5 km/h); Cooldown 5 min @ 8.5 km/h"
        in message
    )


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

    message = narrative_builder.build_weekly_plan_summary(
        rows, week_number=1, week_start=real_date(2024, 9, 2)
    )
    assert (
        "Warmup 5 min @ 8.5 km/h; 20 min @ 10.5 km/h; Cooldown 5 min @ 8.5 km/h"
        in message
    )


def test_weekly_plan_legacy_rows_render_without_treadmill_details():
    rows = [
        {
            "day_of_week": 1,
            "exercise_name": "Bench Press",
            "sets": 5,
            "reps": 5,
            "rir": 2,
        }
    ]
    message = narrative_builder.build_weekly_plan_summary(
        rows, week_number=1, week_start=real_date(2024, 9, 2)
    )
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

    message = narrative_builder.build_weekly_plan_summary(
        rows, week_number=1, week_start=real_date(2024, 9, 2)
    )
    lines = message.splitlines()
    monday_idx = lines.index("Monday:")
    tuesday_idx = len(lines)
    monday_entries = lines[monday_idx + 1 : tuesday_idx]

    joined = "\n".join(monday_entries)
    assert (
        joined.index("Quality run")
        < joined.index("Bench Press")
        < joined.index("Limber 11")
    )
    assert "Seated Piriformis Stretch [isometric]" in joined
    assert "Rear-foot-elevated Hip Flexor Stretch [dynamic + 3s hold]" in joined


def test_weekly_plan_empty_output_is_exact_and_uses_week_number(monkeypatch):
    deterministic = _DeterministicRandom()
    monkeypatch.setattr(narrative_builder, "random", deterministic)
    monkeypatch.setattr(
        narrative_builder, "phrase_for", lambda **_: "Remember to hydrate."
    )

    assert narrative_builder.build_weekly_plan_summary([], week_number=9) == (
        "Yo Ric! Coach Pete's weekly huddle incoming 📅\n"
        "\n"
        "*Week 9 Game Plan*\n"
        "- I couldn't find workouts for this week – ping me once the plan's loaded.\n"
        "Remember to hydrate."
    )


def test_weekly_plan_all_days_and_whitespace_are_exact():
    rows = [
        {"day_of_week": day, "exercise_name": name}
        for day, name in enumerate("ABCDEFG", start=1)
    ]

    assert narrative_builder.build_weekly_plan_summary(rows, week_number=3) == (
        "Cycle week: 3\n"
        "Monday:\nA\n\n"
        "Tuesday:\nB\n\n"
        "Wednesday:\nC\n\n"
        "Thursday:\nD\n\n"
        "Friday:\nE\n\n"
        "Saturday:\nF\n\n"
        "Sunday:\nG"
    )


def test_weekly_plan_day_coercion_range_filter_and_tie_order_are_exact():
    rows = [
        {"exercise_name": "missing"},
        {"day_of_week": None, "exercise_name": "none"},
        {"day_of_week": "", "exercise_name": "blank"},
        {"day_of_week": "invalid", "exercise_name": "invalid"},
        {"day_of_week": 0, "exercise_name": "zero"},
        {"day_of_week": -1, "exercise_name": "negative"},
        {"day_of_week": 8, "exercise_name": "eight"},
        {"day_of_week": 1.9, "exercise_name": "float first"},
        {"day_of_week": True, "exercise_name": "boolean second"},
        {"day_of_week": "2", "exercise_name": "numeric string"},
    ]

    assert narrative_builder.build_weekly_plan_summary(rows, week_number=2) == (
        "Cycle week: 2\n"
        "Monday:\n"
        "float first\n"
        "boolean second\n"
        "\n"
        "Tuesday:\n"
        "numeric string"
    )
    assert (
        narrative_builder.build_weekly_plan_summary(rows[:7], week_number=2)
        == "Cycle week: 2"
    )


def test_weekly_plan_legacy_and_structured_naming_fallbacks_are_exact():
    rows = [
        {"day_of_week": 1},
        {"day_of_week": 1, "exercise_id": 0, "exercise_name": ""},
        {
            "day_of_week": 1,
            "comment": 0,
            "exercise_name": "",
            "details": {"session_type": "unknown"},
        },
        {
            "day_of_week": 1,
            "comment": 123,
            "exercise_name": "ignored",
            "details": {"session_type": "unknown"},
        },
    ]

    assert narrative_builder.build_weekly_plan_summary(rows, week_number=1) == (
        "Cycle week: 1\n" "Monday:\n" "Exercise None\n" "Run\n" "123\n" "Exercise 0"
    )


def test_weekly_plan_detail_truthiness_numeric_and_optional_rules_are_exact():
    rows = [
        {
            "day_of_week": 1,
            "exercise_name": "Zeros",
            "sets": 0,
            "reps": 0,
            "target_weight_kg": 0,
            "weight_kg": 12,
            "rir": 0,
            "rir_cue": 5,
            "optional": 0,
        },
        {
            "day_of_week": 1,
            "exercise_name": "Target",
            "sets": "01.50",
            "reps": "bad",
            "target_weight_kg": "15.0",
            "weight_kg": 99,
            "rir": "2.50",
            "optional": "false",
        },
        {
            "day_of_week": 1,
            "exercise_name": "Empty mapping",
            "sets": 1,
            "reps": 2,
            "target_weight_kg": 7,
            "rir": 3,
            "details": {},
        },
        {
            "day_of_week": 1,
            "comment": "Structured",
            "sets": 1,
            "reps": 2,
            "target_weight_kg": 7,
            "rir": 3,
            "details": {"session_type": "unknown"},
        },
        {
            "day_of_week": 1,
            "exercise_name": "Truthy non-mapping",
            "sets": 1,
            "reps": 2,
            "target_weight_kg": 7,
            "rir": 3,
            "details": ["legacy"],
        },
        {
            "day_of_week": 1,
            "exercise_name": "Falsey non-mapping",
            "sets": 1,
            "reps": 2,
            "target_weight_kg": "",
            "weight_kg": 0,
            "rir": 0,
            "details": [],
        },
        {"day_of_week": 1, "exercise_name": "Cue only", "rir_cue": 4},
    ]

    assert narrative_builder.build_weekly_plan_summary(rows, week_number=1) == (
        "Cycle week: 1\n"
        "Monday:\n"
        "Zeros (0 x 0 · 12 kg · RIR 0)\n"
        "Target (1.5 x bad · 15 kg · RIR 2.5 · optional)\n"
        "Empty mapping (1 x 2 · 7 kg · RIR 3)\n"
        "Structured (1 x 2)\n"
        "Truthy non-mapping (1 x 2)\n"
        "Falsey non-mapping (1 x 2 · 0 kg · RIR 0)\n"
        "Cue only"
    )


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        ({}, None),
        ({"session_type": "easy", "steps": ()}, None),
        ({"session_type": "unknown", "steps": [{}]}, None),
        (
            {"session_type": "intervals", "steps": [None]},
            "Warmup None min @ None km/h; None × (None min @ None km/h, "
            "None min @ None km/h); Cooldown None min @ None km/h",
        ),
        (
            {"session_type": "tempo", "steps": [None]},
            "Warmup None min @ None km/h; None min @ None km/h; "
            "Cooldown None min @ None km/h",
        ),
        (
            {
                "session_type": "easy",
                "steps": [
                    {
                        "duration_minutes": "20.0",
                        "speed_kph": "8",
                        "min_speed_kph": "bad",
                        "max_speed_kph": 9.25,
                    }
                ],
            },
            "20 min @ 8.0 km/h (easy range bad–9.2)",
        ),
        (
            {
                "session_type": "steady",
                "steps": [{"duration_minutes": 35, "speed_kph": 9.9}],
            },
            "35 min @ 9.9 km/h",
        ),
        (
            {
                "session_type": "recovery",
                "steps": [
                    {
                        "duration_minutes": 12,
                        "min_duration_minutes": 0,
                        "max_duration_minutes": 15,
                        "speed_kph": 8.5,
                    }
                ],
            },
            "0–15 min @ 8.5 km/h",
        ),
        (
            {
                "session_type": "recovery",
                "steps": [{"duration_minutes": "12.5", "speed_kph": "slow"}],
            },
            "12.5 min @ slow km/h",
        ),
        (
            {
                "session_type": "long_run",
                "steps": [
                    {
                        "distance_km": "far",
                        "speed_kph": "fast",
                        "min_speed_kph": 8.8,
                        "max_speed_kph": 9.2,
                    }
                ],
            },
            "Long run: far km @ fast km/h (range 8.8–9.2)",
        ),
    ],
)
def test_treadmill_instruction_malformed_variants_are_characterized(details, expected):
    assert narrative_builder._render_treadmill_instruction(details) == expected


def test_treadmill_interval_malformed_nested_step_error_is_preserved():
    details = {
        "session_type": "intervals",
        "steps": [{}, {"steps": ["not-a-mapping"]}, {}],
    }

    with pytest.raises(AttributeError, match="has no attribute 'get'"):
        narrative_builder._render_treadmill_instruction(details)


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        ({}, None),
        ({"session_type": schedule_rules.STRETCH_SESSION_TYPE, "steps": []}, None),
        (
            {
                "session_type": schedule_rules.STRETCH_SESSION_TYPE,
                "display_name": "Mobility",
                "steps": [None, {}, {"name": " "}],
            },
            "Mobility",
        ),
        (
            {
                "session_type": schedule_rules.STRETCH_SESSION_TYPE,
                "steps": [
                    {
                        "name": "Iso",
                        "is_isometric": True,
                        "includes_isometric_hold": True,
                    },
                    {"name": "Missing hold", "includes_isometric_hold": True},
                    {
                        "name": "Zero hold",
                        "includes_isometric_hold": True,
                        "hold_seconds": 0,
                    },
                    {"name": "Dynamic"},
                ],
            },
            "Stretch routine: Iso [isometric]; Missing hold [dynamic + holds]; "
            "Zero hold [dynamic + 0s hold]; Dynamic [dynamic]",
        ),
        (
            {
                "session_type": schedule_rules.STRETCH_SESSION_TYPE,
                "display_name": "   ",
                "steps": [{"name": 12}],
            },
            ": 12 [dynamic]",
        ),
    ],
)
def test_stretch_instruction_malformed_and_style_variants_are_characterized(
    details, expected
):
    assert narrative_builder._render_stretch_instruction(details) == expected


def test_weekly_plan_rest_week_start_and_delimiters_are_exact():
    rows = [
        {"day_of_week": 1, "exercise_name": "Lift: press | Pull || Finish"},
        {
            "day_of_week": 7,
            "comment": "Long: run",
            "details": {"session_type": "unknown"},
        },
    ]

    day_lines, rest_days = narrative_builder._format_weekly_workouts(rows)
    expected = (
        "Cycle week: 6\n"
        "Monday:\n"
        "Lift: press\n"
        "Pull\n"
        "Finish\n"
        "\n"
        "Sunday:\n"
        "Long: run"
    )

    assert day_lines == [
        "- Monday: Lift: press | Pull || Finish",
        "- Sunday: Long: run",
    ]
    assert rest_days == ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    assert narrative_builder.build_weekly_plan_summary(rows, week_number=6) == expected
    assert (
        narrative_builder.build_weekly_plan_summary(
            rows,
            week_number=6,
            week_start=real_date(1999, 12, 27),
        )
        == expected
    )
    assert "Rest windows" not in expected


def test_weekly_plan_sequence_and_non_mapping_entry_assumptions_are_preserved():
    rows = ({"day_of_week": 1, "exercise_name": "Generator row"} for _ in range(1))
    empty_rows = (row for row in [])

    assert narrative_builder.build_weekly_plan_summary(rows, week_number=4) == (
        "Cycle week: 4\nMonday:\nGenerator row"
    )
    assert (
        narrative_builder.build_weekly_plan_summary(empty_rows, week_number=4)
        == "Cycle week: 4"
    )
    with pytest.raises(AttributeError, match="has no attribute 'get'"):
        narrative_builder.build_weekly_plan_summary(["not-a-row"], week_number=4)


def test_weekly_plan_compatibility_facades_match_exact_summary():
    rows = [{"day_of_week": 3, "exercise_name": "Tempo: run | cooldown"}]
    expected = "Cycle week: 8\nWednesday:\nTempo: run\ncooldown"

    assert narrative_builder.PeteVoice.plan(rows, 8, real_date(2024, 9, 2)) == expected
    assert (
        narrative_builder.NarrativeBuilder().build_weekly_plan(
            rows,
            8,
            real_date(2024, 9, 2),
        )
        == expected
    )


@pytest.mark.contract
def test_weekly_plan_cli_print_output_is_exact(monkeypatch):
    _setup(monkeypatch)

    result = runner.invoke(messenger.app, ["message", "--plan"], catch_exceptions=False)

    assert result.exit_code == 0
    assert result.stdout == (
        "--- Weekly Plan ---\n"
        "Cycle week: 1\n"
        "Monday:\n"
        "Squat (3 x 5 · RIR 2)\n"
        "Bench Press (3 x 8 · RIR 1)\n"
        "\n"
        "Wednesday:\n"
        "Tempo Run\n"
    )


@pytest.mark.contract
def test_weekly_plan_cli_send_failure_keeps_rendered_output_and_exits_one(monkeypatch):
    orch = _setup(monkeypatch)
    monkeypatch.setattr(orch, "send_telegram_message", lambda _message: False)

    result = runner.invoke(messenger.app, ["message", "--plan", "--send"])

    assert result.exit_code == 1
    assert "Cycle week: 1\nMonday:\nSquat (3 x 5 · RIR 2)" in result.stdout
