"""Exact compatibility characterization for the public metric-trend facade."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, cast

import pytest

from pete_e.domain import narrative_builder


TARGET = date(2026, 8, 23)
STEPS_STEADY_FORMING = (
    "Steps trend: 10,000 steps/day "
    "(steady vs 30d avg 10,000 steps/day; 60d base still forming)."
)
SLEEP_STEADY_FORMING = (
    "Sleep trend: 7.0 h/night "
    "(steady vs 30d avg 7.0 h/night; 60d base still forming)."
)
STEPS_STEADY_BASE = (
    "Steps trend: 10,000 steps/day "
    "(steady vs 30d avg 10,000 steps/day; 60d base 10,000 steps/day)."
)
SLEEP_STEADY_BASE = (
    "Sleep trend: 7.0 h/night " "(steady vs 30d avg 7.0 h/night; 60d base 7.0 h/night)."
)


def _payload(*, steps: object = 10_000.0, sleep: object = 420.0) -> dict[str, object]:
    return {"steps": steps, "sleep_asleep_minutes": sleep}


def _counted_samples(
    *,
    week_count: int,
    month_count: int,
    baseline_count: int = 0,
) -> list[tuple[date, dict[str, object]]]:
    assert week_count <= month_count <= 30
    assert baseline_count <= 60
    rows = [
        (TARGET - timedelta(days=offset), _payload()) for offset in range(week_count)
    ]
    rows.extend(
        (TARGET - timedelta(days=offset), _payload())
        for offset in range(7, 7 + month_count - week_count)
    )
    rows.extend(
        (TARGET - timedelta(days=offset), _payload())
        for offset in range(30, 30 + baseline_count)
    )
    return rows


def _metric_payload(metric: str, value: float) -> dict[str, object]:
    if metric == "Steps":
        return {"activity": {"steps": value}}
    return {"sleep": {"asleep_minutes": value}}


def _current_threshold_samples(
    metric: str,
    delta: float,
    *,
    negative: bool = False,
) -> list[tuple[date, dict[str, object]]]:
    base = 10_000.0 if metric == "Steps" else 420.0
    recent_change = delta * 30.0 / 23.0
    recent = base - recent_change if negative else base + recent_change
    return [
        (
            TARGET - timedelta(days=offset),
            _metric_payload(metric, recent if offset < 7 else base),
        )
        for offset in range(30)
    ]


def _baseline_threshold_samples(
    metric: str,
    baseline: float,
    *,
    baseline_count: int = 21,
) -> list[tuple[date, dict[str, object]]]:
    current = 10_000.0 if metric == "Steps" else 420.0
    rows = [
        (TARGET - timedelta(days=offset), _metric_payload(metric, current))
        for offset in range(30)
    ]
    rows.extend(
        (TARGET - timedelta(days=offset), _metric_payload(metric, baseline))
        for offset in range(30, 30 + baseline_count)
    )
    return rows


def _metric_line(metric: str, rows: list[tuple[date, dict[str, object]]]) -> str:
    lines = narrative_builder.compute_trend_lines(rows, as_of=TARGET)
    return lines[0] if metric == "Steps" else lines[1]


def test_empty_and_rows_without_a_valid_date_payload_pair_return_empty() -> None:
    assert narrative_builder.compute_trend_lines([]) == []

    invalid_rows = cast(
        Any,
        [
            ("not-a-date", {}),
            (object(), {}),
            (TARGET, []),
            (datetime.combine(TARGET, time.min), None),
        ],
    )
    assert narrative_builder.compute_trend_lines(invalid_rows) == []


def test_valid_rows_without_metric_values_render_ordered_no_data_messages() -> None:
    rows = cast(
        Any,
        [
            (TARGET, {}),
            (TARGET - timedelta(days=1), {"steps": "invalid"}),
            (TARGET - timedelta(days=2), {"sleep_asleep_minutes": object()}),
        ],
    )

    assert narrative_builder.compute_trend_lines(rows, as_of=TARGET) == [
        "Steps trend: no data logged yet.",
        "Sleep trend: no data logged yet.",
    ]


def test_datetime_converter_dates_unordered_duplicates_and_future_filtering() -> None:
    raw_rows: list[tuple[object, object]] = [
        (TARGET - timedelta(days=offset), _payload()) for offset in range(7, 23)
    ]
    raw_rows.extend(
        [
            (datetime.combine(TARGET, time(23, 59)), _payload()),
            (f"{(TARGET - timedelta(days=1)).isoformat()}T12:30:00Z", _payload()),
            (TARGET - timedelta(days=2), _payload()),
            (TARGET - timedelta(days=2), _payload()),
            (TARGET + timedelta(days=1), _payload(steps=999_999, sleep=9_999)),
            ("invalid", _payload()),
            (TARGET, []),
        ]
    )
    raw_rows.reverse()

    assert narrative_builder.compute_trend_lines(cast(Any, raw_rows), as_of=TARGET) == [
        STEPS_STEADY_FORMING,
        SLEEP_STEADY_FORMING,
    ]


def test_default_as_of_uses_latest_normalized_row_even_when_it_is_future() -> None:
    rows = [(TARGET - timedelta(days=offset), _payload()) for offset in range(20)]
    rows.append((TARGET + timedelta(days=100), _payload()))

    assert narrative_builder.compute_trend_lines(rows) == [
        "Steps trend: need more data logged (only 1 days in last 30d).",
        "Sleep trend: need more data logged (only 1 days in last 30d).",
    ]
    assert narrative_builder.compute_trend_lines(rows, as_of=TARGET) == [
        STEPS_STEADY_FORMING,
        SLEEP_STEADY_FORMING,
    ]


def test_all_inclusive_window_boundaries_and_adjacent_exclusions() -> None:
    rows: list[tuple[date, dict[str, object]]] = []
    for offset in range(30):
        steps = 10_000.0
        sleep = 420.0
        if offset == 6:
            steps, sleep = 13_000.0, 430.0
        elif offset == 7:
            steps, sleep = 14_000.0, 440.0
        elif offset == 29:
            steps, sleep = 15_000.0, 450.0
        rows.append(
            (TARGET - timedelta(days=offset), _payload(steps=steps, sleep=sleep))
        )
    for offset in range(30, 50):
        values = (8_000.0, 380.0) if offset == 30 else (9_000.0, 390.0)
        rows.append(
            (
                TARGET - timedelta(days=offset),
                _payload(steps=values[0], sleep=values[1]),
            )
        )
    rows.extend(
        [
            (TARGET - timedelta(days=89), _payload(steps=7_000, sleep=360)),
            (TARGET - timedelta(days=90), _payload(steps=999_999, sleep=9_999)),
            (TARGET + timedelta(days=1), _payload(steps=999_999, sleep=9_999)),
        ]
    )

    assert narrative_builder.compute_trend_lines(rows, as_of=TARGET) == [
        "Steps trend: 10,429 steps/day (steady vs 30d avg 10,400 steps/day; "
        "up 1,543 steps vs 60d base 8,857 steps/day).",
        "Sleep trend: 7.0 h/night (steady vs 30d avg 7.0 h/night; "
        "up 0.6 h vs 60d base 6.5 h/night).",
    ]


def test_nested_paths_precede_flat_paths_and_numeric_strings_are_accepted() -> None:
    payload = {
        "activity": {"steps": "12345.6"},
        "steps": "1",
        "sleep": {"asleep_minutes": "425"},
        "sleep_asleep_minutes": "1",
    }

    assert narrative_builder.compute_trend_lines([(TARGET, payload)] * 20) == [
        "Steps trend: 12,346 steps/day (steady vs 30d avg 12,346 steps/day; "
        "60d base still forming).",
        "Sleep trend: 7.1 h/night (steady vs 30d avg 7.1 h/night; "
        "60d base still forming).",
    ]


@pytest.mark.parametrize("nested_steps", [None, "invalid", 0, -1])
@pytest.mark.parametrize("nested_sleep", [None, "invalid", 0, -1])
def test_invalid_nested_values_fall_back_to_positive_flat_values(
    nested_steps: object,
    nested_sleep: object,
) -> None:
    payload = {
        "activity": {"steps": nested_steps},
        "steps": 10_000,
        "sleep": {"asleep_minutes": nested_sleep},
        "sleep_asleep_minutes": 420,
    }

    assert narrative_builder.compute_trend_lines([(TARGET, payload)] * 20) == [
        STEPS_STEADY_FORMING,
        SLEEP_STEADY_FORMING,
    ]


@pytest.mark.parametrize("value", [0, -1, "0", "-1", "invalid", None])
def test_zero_negative_and_invalid_values_are_excluded(value: object) -> None:
    payload = {
        "activity": {"steps": value},
        "steps": value,
        "sleep": {"asleep_minutes": value},
        "sleep_asleep_minutes": value,
    }

    assert narrative_builder.compute_trend_lines([(TARGET, payload)] * 20) == [
        "Steps trend: no data logged yet.",
        "Sleep trend: no data logged yet.",
    ]


@pytest.mark.parametrize(("value", "rendered"), [("nan", "nan"), ("inf", "inf")])
def test_non_finite_numeric_strings_keep_python_float_behavior(
    value: str,
    rendered: str,
) -> None:
    payload = {"steps": value, "sleep_asleep_minutes": value}

    assert narrative_builder.compute_trend_lines([(TARGET, payload)] * 20) == [
        f"Steps trend: {rendered} steps/day "
        f"(steady vs 30d avg {rendered} steps/day; 60d base still forming).",
        f"Sleep trend: {rendered} h/night "
        f"(steady vs 30d avg {rendered} h/night; 60d base still forming).",
    ]


@pytest.mark.parametrize(
    ("week_count", "month_count", "expected"),
    [
        (3, 20, "need more data logged (only 20 days in last 30d)"),
        (4, 20, "10,000 steps/day"),
        (5, 21, "10,000 steps/day"),
    ],
)
def test_week_sample_minimum_below_at_and_above(
    week_count: int,
    month_count: int,
    expected: str,
) -> None:
    lines = narrative_builder.compute_trend_lines(
        _counted_samples(week_count=week_count, month_count=month_count),
        as_of=TARGET,
    )

    assert expected in lines[0]
    if "need more data" in expected:
        assert expected in lines[1]
    else:
        assert lines == [STEPS_STEADY_FORMING, SLEEP_STEADY_FORMING]


@pytest.mark.parametrize(
    ("month_count", "expected"),
    [
        (19, "need more data logged (only 19 days in last 30d)"),
        (20, "10,000 steps/day"),
        (21, "10,000 steps/day"),
    ],
)
def test_month_sample_minimum_below_at_and_above(
    month_count: int,
    expected: str,
) -> None:
    lines = narrative_builder.compute_trend_lines(
        _counted_samples(week_count=4, month_count=month_count),
        as_of=TARGET,
    )

    assert expected in lines[0]
    if "need more data" in expected:
        assert expected in lines[1]
    else:
        assert lines == [STEPS_STEADY_FORMING, SLEEP_STEADY_FORMING]


@pytest.mark.parametrize(
    ("baseline_count", "expected_steps", "expected_sleep"),
    [
        (20, STEPS_STEADY_FORMING, SLEEP_STEADY_FORMING),
        (21, STEPS_STEADY_BASE, SLEEP_STEADY_BASE),
        (22, STEPS_STEADY_BASE, SLEEP_STEADY_BASE),
    ],
)
def test_baseline_sample_minimum_below_at_and_above(
    baseline_count: int,
    expected_steps: str,
    expected_sleep: str,
) -> None:
    assert narrative_builder.compute_trend_lines(
        _counted_samples(
            week_count=4,
            month_count=20,
            baseline_count=baseline_count,
        ),
        as_of=TARGET,
    ) == [expected_steps, expected_sleep]


def test_duplicate_rows_count_as_logged_days_and_can_meet_both_minima() -> None:
    assert narrative_builder.compute_trend_lines([(TARGET, _payload())] * 20) == [
        STEPS_STEADY_FORMING,
        SLEEP_STEADY_FORMING,
    ]
    assert narrative_builder.compute_trend_lines([(TARGET, _payload())] * 3) == [
        "Steps trend: need more data logged (only 3 days in last 30d).",
        "Sleep trend: need more data logged (only 3 days in last 30d).",
    ]


def test_sparse_logged_count_falls_back_to_all_filtered_samples() -> None:
    old_day = TARGET - timedelta(days=100)

    assert narrative_builder.compute_trend_lines(
        [(old_day, _payload())], as_of=TARGET
    ) == [
        "Steps trend: need more data logged (only 1 days in last 30d).",
        "Sleep trend: need more data logged (only 1 days in last 30d).",
    ]


@pytest.mark.parametrize(
    ("metric", "delta", "negative", "expected"),
    [
        (
            "Steps",
            399.999,
            False,
            "Steps trend: 10,522 steps/day (steady vs 30d avg 10,122 steps/day; "
            "60d base still forming).",
        ),
        (
            "Steps",
            400.0,
            False,
            "Steps trend: 10,522 steps/day (up 400 steps vs 30d avg 10,122 steps/day; "
            "60d base still forming).",
        ),
        (
            "Steps",
            400.001,
            False,
            "Steps trend: 10,522 steps/day (up 400 steps vs 30d avg 10,122 steps/day; "
            "60d base still forming).",
        ),
        (
            "Steps",
            399.999,
            True,
            "Steps trend: 9,478 steps/day (steady vs 30d avg 9,878 steps/day; "
            "60d base still forming).",
        ),
        (
            "Steps",
            400.0,
            True,
            "Steps trend: 9,478 steps/day (down 400 steps vs 30d avg 9,878 steps/day; "
            "60d base still forming).",
        ),
        (
            "Steps",
            400.001,
            True,
            "Steps trend: 9,478 steps/day (down 400 steps vs 30d avg 9,878 steps/day; "
            "60d base still forming).",
        ),
        (
            "Sleep",
            5.999,
            False,
            "Sleep trend: 7.1 h/night (steady vs 30d avg 7.0 h/night; "
            "60d base still forming).",
        ),
        (
            "Sleep",
            6.0,
            False,
            "Sleep trend: 7.1 h/night (up 0.1 h vs 30d avg 7.0 h/night; "
            "60d base still forming).",
        ),
        (
            "Sleep",
            6.001,
            False,
            "Sleep trend: 7.1 h/night (up 0.1 h vs 30d avg 7.0 h/night; "
            "60d base still forming).",
        ),
        (
            "Sleep",
            5.999,
            True,
            "Sleep trend: 6.9 h/night (steady vs 30d avg 7.0 h/night; "
            "60d base still forming).",
        ),
        (
            "Sleep",
            6.0,
            True,
            "Sleep trend: 6.9 h/night (down 0.1 h vs 30d avg 7.0 h/night; "
            "60d base still forming).",
        ),
        (
            "Sleep",
            6.001,
            True,
            "Sleep trend: 6.9 h/night (down 0.1 h vs 30d avg 7.0 h/night; "
            "60d base still forming).",
        ),
    ],
)
def test_current_significance_below_at_above_and_negative_boundaries(
    metric: str,
    delta: float,
    negative: bool,
    expected: str,
) -> None:
    assert (
        _metric_line(
            metric,
            _current_threshold_samples(metric, delta, negative=negative),
        )
        == expected
    )


@pytest.mark.parametrize(
    ("metric", "baseline", "expected"),
    [
        (
            "Steps",
            9_800.001,
            "Steps trend: 10,000 steps/day (steady vs 30d avg 10,000 steps/day; "
            "60d base 9,800 steps/day).",
        ),
        (
            "Steps",
            9_800.0,
            "Steps trend: 10,000 steps/day (steady vs 30d avg 10,000 steps/day; "
            "up 200 steps vs 60d base 9,800 steps/day).",
        ),
        (
            "Steps",
            9_799.999,
            "Steps trend: 10,000 steps/day (steady vs 30d avg 10,000 steps/day; "
            "up 200 steps vs 60d base 9,800 steps/day).",
        ),
        (
            "Steps",
            10_199.999,
            "Steps trend: 10,000 steps/day (steady vs 30d avg 10,000 steps/day; "
            "60d base 10,200 steps/day).",
        ),
        (
            "Steps",
            10_200.0,
            "Steps trend: 10,000 steps/day (steady vs 30d avg 10,000 steps/day; "
            "down 200 steps vs 60d base 10,200 steps/day).",
        ),
        (
            "Steps",
            10_200.001,
            "Steps trend: 10,000 steps/day (steady vs 30d avg 10,000 steps/day; "
            "down 200 steps vs 60d base 10,200 steps/day).",
        ),
        (
            "Sleep",
            417.001,
            "Sleep trend: 7.0 h/night (steady vs 30d avg 7.0 h/night; "
            "60d base 7.0 h/night).",
        ),
        (
            "Sleep",
            417.0,
            "Sleep trend: 7.0 h/night (steady vs 30d avg 7.0 h/night; "
            "up 0.1 h vs 60d base 7.0 h/night).",
        ),
        (
            "Sleep",
            416.999,
            "Sleep trend: 7.0 h/night (steady vs 30d avg 7.0 h/night; "
            "up 0.1 h vs 60d base 6.9 h/night).",
        ),
        (
            "Sleep",
            422.999,
            "Sleep trend: 7.0 h/night (steady vs 30d avg 7.0 h/night; "
            "60d base 7.0 h/night).",
        ),
        (
            "Sleep",
            423.0,
            "Sleep trend: 7.0 h/night (steady vs 30d avg 7.0 h/night; "
            "down 0.1 h vs 60d base 7.0 h/night).",
        ),
        (
            "Sleep",
            423.001,
            "Sleep trend: 7.0 h/night (steady vs 30d avg 7.0 h/night; "
            "down 0.1 h vs 60d base 7.1 h/night).",
        ),
    ],
)
def test_baseline_half_significance_below_at_above_and_down_boundaries(
    metric: str,
    baseline: float,
    expected: str,
) -> None:
    assert (
        _metric_line(metric, _baseline_threshold_samples(metric, baseline)) == expected
    )


def test_baseline_absent_and_forming_have_the_same_exact_public_prose() -> None:
    absent = _baseline_threshold_samples("Steps", 9_000, baseline_count=0)
    forming = _baseline_threshold_samples("Steps", 9_000, baseline_count=20)

    assert _metric_line("Steps", absent) == STEPS_STEADY_FORMING
    assert _metric_line("Steps", forming) == STEPS_STEADY_FORMING


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (None, [STEPS_STEADY_FORMING, SLEEP_STEADY_FORMING]),
        (0, []),
        (1, [STEPS_STEADY_FORMING]),
        (99, [STEPS_STEADY_FORMING, SLEEP_STEADY_FORMING]),
        (-1, [STEPS_STEADY_FORMING]),
    ],
)
def test_limit_preserves_python_slice_behavior(
    limit: int | None,
    expected: list[str],
) -> None:
    rows = _counted_samples(week_count=4, month_count=20)

    assert (
        narrative_builder.compute_trend_lines(rows, as_of=TARGET, limit=limit)
        == expected
    )


def test_sentence_normalization_runs_for_both_lines_before_limit_slicing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered: list[str] = []

    def mark_sentence(text: str) -> str:
        rendered.append(text)
        return f"<{text}>"

    monkeypatch.setattr(narrative_builder.formatters, "ensure_sentence", mark_sentence)

    assert narrative_builder.compute_trend_lines(
        _counted_samples(week_count=4, month_count=20),
        as_of=TARGET,
        limit=1,
    ) == [f"<{STEPS_STEADY_FORMING}>"]
    assert rendered == [STEPS_STEADY_FORMING, SLEEP_STEADY_FORMING]
