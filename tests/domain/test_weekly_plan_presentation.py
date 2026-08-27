"""Pure tests for the typed weekly workout presentation boundary."""

from dataclasses import FrozenInstanceError

import pytest

from pete_e.domain import schedule_rules
from pete_e.domain import weekly_plan_presentation as presentation


def _build(rows):
    return presentation.build_weekly_plan_presentation(
        rows,
        workout_display_order=schedule_rules.workout_display_order,
        stretch_session_type=schedule_rules.STRETCH_SESSION_TYPE,
    )


def test_typed_model_is_immutable_complete_and_stably_ordered():
    rows = [
        {"day_of_week": 1, "exercise_name": "Assistance", "exercise_id": 137},
        {
            "day_of_week": 1,
            "exercise_name": "Main second",
            "exercise_id": schedule_rules.BENCH_ID,
        },
        {
            "day_of_week": 1,
            "exercise_name": "Main third",
            "exercise_id": schedule_rules.SQUAT_ID,
        },
        {
            "day_of_week": 1,
            "comment": "Run first",
            "is_cardio": True,
            "details": {
                "session_type": "easy",
                "steps": [{"duration_minutes": 20, "speed_kph": 9}],
            },
        },
        {
            "day_of_week": 1,
            "comment": "Stretch last",
            "type": schedule_rules.MOBILITY_WORKOUT_TYPE,
            "details": {
                "session_type": schedule_rules.STRETCH_SESSION_TYPE,
                "steps": [{"name": "Move"}],
            },
        },
    ]

    model = _build(rows)

    assert tuple(day.name for day in model.days) == tuple(
        presentation.DAY_NAMES.values()
    )
    assert [session.name for session in model.days[0].sessions] == [
        "Run first",
        "Main second",
        "Main third",
        "Assistance",
        "Stretch last",
    ]
    assert [session.source_position for session in model.days[0].sessions] == [
        3,
        1,
        2,
        0,
        4,
    ]
    assert model.rest_day_names == (
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )
    with pytest.raises(FrozenInstanceError):
        model.days = ()


def test_row_normalization_passes_only_ordering_policy_fields():
    calls = []

    def order_policy(**kwargs):
        calls.append(kwargs)
        return 17

    row = {
        "day_of_week": "2",
        "exercise_id": 42,
        "exercise_name": "Lift",
        "is_cardio": "yes",
        "type": "weights",
        "details": [],
        "sets": 3,
        "reps": 5,
    }

    session = presentation.normalize_weekly_plan_row(
        row,
        source_position=6,
        workout_display_order=order_policy,
        stretch_session_type=schedule_rules.STRETCH_SESSION_TYPE,
    )

    assert session == presentation.WeeklyPlanSession(
        day_number=2,
        name="Lift",
        details=("3 x 5",),
        display_order=17,
        source_position=6,
    )
    assert calls == [
        {
            "is_cardio": True,
            "exercise_id": 42,
            "workout_type": "weights",
            "details": None,
        }
    ]


@pytest.mark.parametrize("day_value", [None, "", "bad", 0, 8])
def test_invalid_day_rows_are_removed_before_ordering(day_value):
    def unexpected_order(**_kwargs):
        raise AssertionError("ordering must not run for an invalid day")

    assert (
        presentation.normalize_weekly_plan_row(
            {"day_of_week": day_value},
            source_position=0,
            workout_display_order=unexpected_order,
            stretch_session_type=schedule_rules.STRETCH_SESSION_TYPE,
        )
        is None
    )


def test_structured_and_legacy_details_normalize_without_losing_truthiness_rules():
    rows = [
        {
            "day_of_week": 1,
            "exercise_name": "Legacy",
            "sets": 0,
            "reps": 0,
            "target_weight_kg": 0,
            "weight_kg": 10,
            "rir": 0,
            "optional": True,
        },
        {
            "day_of_week": 1,
            "comment": "Structured",
            "sets": 3,
            "reps": 8,
            "target_weight_kg": 20,
            "rir": 2,
            "details": {"session_type": "unknown"},
        },
    ]

    sessions = _build(rows).days[0].sessions

    assert sessions[0].details == ("0 x 0", "10 kg", "RIR 0", "optional")
    assert sessions[1].details == ("3 x 8",)
    assert presentation.render_session_text(sessions[0]) == (
        "Legacy (0 x 0 · 10 kg · RIR 0 · optional)"
    )


def test_interval_and_tempo_render_exact_instructions():
    interval_steps = [
        {"duration_minutes": 5, "speed_kph": 8.5},
        {
            "repeats": 5,
            "steps": [
                {"duration_minutes": 3, "speed_kph": 11.5},
                {"duration_minutes": 2, "speed_kph": 8.5},
            ],
        },
        {"duration_minutes": 5, "speed_kph": 8.5},
    ]
    tempo_steps = [
        {"duration_minutes": 5, "speed_kph": 8.5},
        {"duration_minutes": 20, "speed_kph": 10.5},
        {"duration_minutes": 5, "speed_kph": 8.5},
    ]

    assert presentation.render_treadmill_instruction(
        {"session_type": "intervals", "steps": interval_steps}
    ) == (
        "Warmup 5 min @ 8.5 km/h; 5 × (3 min @ 11.5 km/h, "
        "2 min @ 8.5 km/h); Cooldown 5 min @ 8.5 km/h"
    )
    assert presentation.render_treadmill_instruction(
        {"session_type": "tempo", "steps": tempo_steps}
    ) == ("Warmup 5 min @ 8.5 km/h; 20 min @ 10.5 km/h; " "Cooldown 5 min @ 8.5 km/h")


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        (
            {
                "session_type": "easy",
                "steps": [
                    {
                        "duration_minutes": 20,
                        "speed_kph": 8.9,
                        "min_speed_kph": 8.8,
                        "max_speed_kph": 9,
                    }
                ],
            },
            "20 min @ 8.9 km/h (easy range 8.8–9.0)",
        ),
        (
            {
                "session_type": "steady",
                "steps": [
                    {
                        "duration_minutes": 35,
                        "speed_kph": 9.9,
                        "min_speed_kph": 9.8,
                        "max_speed_kph": 10,
                    }
                ],
            },
            "35 min @ 9.9 km/h (steady range 9.8–10.0)",
        ),
        (
            {
                "session_type": "recovery",
                "steps": [{"duration_minutes": 12, "speed_kph": 8.5}],
            },
            "12 min @ 8.5 km/h",
        ),
        (
            {
                "session_type": "long_run",
                "steps": [{"distance_km": 8, "speed_kph": 9}],
            },
            "Long run: 8 km @ 9.0 km/h",
        ),
        ({"session_type": "mystery", "steps": [{}]}, None),
        ({"session_type": "easy", "steps": []}, None),
    ],
)
def test_other_treadmill_variants(details, expected):
    assert presentation.render_treadmill_instruction(details) == expected


def test_stretch_renderer_skips_malformed_steps_and_preserves_styles():
    details = {
        "session_type": schedule_rules.STRETCH_SESSION_TYPE,
        "display_name": "Flow",
        "steps": [
            None,
            {"name": ""},
            {"name": "Iso", "is_isometric": True},
            {"name": "Hold", "includes_isometric_hold": True},
            {"name": "Timed", "includes_isometric_hold": True, "hold_seconds": 3},
            {"name": "Move"},
        ],
    }

    assert presentation.render_stretch_instruction(
        details,
        stretch_session_type=schedule_rules.STRETCH_SESSION_TYPE,
    ) == (
        "Flow: Iso [isometric]; Hold [dynamic + holds]; "
        "Timed [dynamic + 3s hold]; Move [dynamic]"
    )


def test_final_layout_applies_explicit_pipe_compatibility_without_day_reparsing():
    model = _build(
        [
            {"day_of_week": 1, "exercise_name": "Press: top | backoff || "},
            {"day_of_week": 3, "exercise_name": "Tempo: steady"},
        ]
    )

    assert presentation.render_weekly_plan_summary(model, week_number=5) == (
        "Cycle week: 5\n"
        "Monday:\n"
        "Press: top\n"
        "backoff\n"
        "\n"
        "Wednesday:\n"
        "Tempo: steady"
    )
    assert presentation.render_compatibility_workout_lines(model) == (
        [
            "- Monday: Press: top | backoff || ",
            "- Wednesday: Tempo: steady",
        ],
        ["Tuesday", "Thursday", "Friday", "Saturday", "Sunday"],
    )
