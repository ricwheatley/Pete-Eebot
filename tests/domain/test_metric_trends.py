"""Pure tests for typed metric-trend normalization, policy, and rendering."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from math import nan
from typing import Any, cast

import pytest

from pete_e.domain import metric_trends
from pete_e.utils import converters, formatters


TARGET = date(2026, 8, 23)


def _statistics(
    *,
    filtered_count: int = 20,
    week_count: int = 4,
    week_average: float | None = 10_000.0,
    month_count: int = 20,
    month_average: float | None = 10_000.0,
    baseline_count: int = 0,
    baseline_average: float | None = None,
) -> metric_trends.TrendWindowStatistics:
    return metric_trends.TrendWindowStatistics(
        filtered_sample_count=filtered_count,
        week=metric_trends.WindowStatistic(week_count, week_average),
        month=metric_trends.WindowStatistic(month_count, month_average),
        baseline=metric_trends.WindowStatistic(baseline_count, baseline_average),
    )


def _decision(
    definition: metric_trends.MetricDefinition,
    **statistics: object,
) -> metric_trends.MetricTrendDecision:
    return metric_trends.decide_metric_trend(
        definition,
        _statistics(**statistics),  # type: ignore[arg-type]
    )


def test_metric_policy_table_is_exact_and_ordered() -> None:
    assert metric_trends.METRIC_DEFINITIONS == (
        metric_trends.MetricDefinition(
            metric=metric_trends.TrendMetric.STEPS,
            paths=(("activity", "steps"), ("steps",)),
            significance=400.0,
        ),
        metric_trends.MetricDefinition(
            metric=metric_trends.TrendMetric.SLEEP,
            paths=(("sleep", "asleep_minutes"), ("sleep_asleep_minutes",)),
            significance=6.0,
        ),
    )
    for definition in metric_trends.METRIC_DEFINITIONS:
        assert definition.min_week_samples == 4
        assert definition.min_month_samples == 20
        assert definition.min_baseline_samples == 21
        assert definition.include_zero is False


def test_boundary_values_are_immutable() -> None:
    sample = metric_trends.NormalizedTrendSample(TARGET, 10_000.0, 420.0)
    decision = _decision(metric_trends.STEPS)

    with pytest.raises(FrozenInstanceError):
        sample.steps = 1.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.status = metric_trends.TrendStatus.NO_DATA  # type: ignore[misc]


def test_normalization_resolves_paths_once_sorts_and_retains_duplicates() -> None:
    parser_inputs: list[object] = []

    def parse_date(value: object) -> date | None:
        parser_inputs.append(value)
        return converters.to_date(value)

    raw_rows = cast(
        Any,
        [
            (
                "2026-08-22T23:00:00Z",
                {
                    "activity": {"steps": "12345.5"},
                    "steps": 1,
                    "sleep": {"asleep_minutes": 0},
                    "sleep_asleep_minutes": "425",
                },
            ),
            (datetime(2026, 8, 21, 23, 59), {"steps": 9_000, "sleep": 390}),
            (TARGET, {"activity": "invalid", "steps": 8_000}),
            (TARGET, {}),
            ("invalid", {}),
            (TARGET, []),
        ],
    )

    assert metric_trends.normalize_samples(raw_rows, parse_date=parse_date) == (
        metric_trends.NormalizedTrendSample(date(2026, 8, 21), 9_000.0, None),
        metric_trends.NormalizedTrendSample(date(2026, 8, 22), 12_345.5, 425.0),
        metric_trends.NormalizedTrendSample(TARGET, 8_000.0, None),
        metric_trends.NormalizedTrendSample(TARGET, None, None),
    )
    assert parser_inputs == ["2026-08-22T23:00:00Z", "invalid"]


def test_normalize_sample_rejects_invalid_parser_result_and_payload() -> None:
    assert (
        metric_trends.normalize_sample(
            "invalid",
            {},
            parse_date=lambda _: None,
        )
        is None
    )
    assert (
        metric_trends.normalize_sample(
            TARGET,
            [],
            parse_date=lambda _: TARGET,
        )
        is None
    )


def test_resolver_can_honor_the_existing_include_zero_policy_field() -> None:
    definition = metric_trends.MetricDefinition(
        metric=metric_trends.TrendMetric.STEPS,
        paths=(("value",),),
        significance=1.0,
        include_zero=True,
    )

    assert metric_trends.resolve_metric_value({"value": 0}, definition) == 0.0
    assert metric_trends.resolve_metric_value({"value": -2}, definition) == -2.0


def test_metric_sample_selection_and_mean_are_independent() -> None:
    sample = metric_trends.NormalizedTrendSample(TARGET, 10_000.0, 420.0)

    assert (
        metric_trends.metric_sample_value(sample, metric_trends.TrendMetric.STEPS)
        == 10_000.0
    )
    assert (
        metric_trends.metric_sample_value(sample, metric_trends.TrendMetric.SLEEP)
        == 420.0
    )
    assert metric_trends.mean_value(()) is None
    assert metric_trends.mean_value((1.0, 2.0, 6.0)) == 3.0


def test_window_statistics_pin_every_inclusive_edge_and_duplicate_count() -> None:
    samples = (
        metric_trends.NormalizedTrendSample(TARGET + timedelta(days=1), 999.0, None),
        metric_trends.NormalizedTrendSample(TARGET, 1.0, None),
        metric_trends.NormalizedTrendSample(TARGET, 3.0, None),
        metric_trends.NormalizedTrendSample(TARGET - timedelta(days=6), 7.0, None),
        metric_trends.NormalizedTrendSample(TARGET - timedelta(days=7), 8.0, None),
        metric_trends.NormalizedTrendSample(TARGET - timedelta(days=29), 30.0, None),
        metric_trends.NormalizedTrendSample(TARGET - timedelta(days=30), 31.0, None),
        metric_trends.NormalizedTrendSample(TARGET - timedelta(days=89), 90.0, None),
        metric_trends.NormalizedTrendSample(TARGET - timedelta(days=90), 91.0, None),
    )

    statistics = metric_trends.calculate_window_statistics(
        metric_trends.STEPS,
        samples,
        TARGET,
    )

    assert statistics.filtered_sample_count == 8
    assert statistics.week == metric_trends.WindowStatistic(3, 11.0 / 3.0)
    assert statistics.month == metric_trends.WindowStatistic(5, 9.8)
    assert statistics.baseline == metric_trends.WindowStatistic(2, 60.5)


def test_analysis_is_empty_without_samples_and_defaults_to_latest_sample_day() -> None:
    assert metric_trends.analyze_trends(()) == ()
    samples = tuple(
        metric_trends.NormalizedTrendSample(
            TARGET - timedelta(days=offset),
            10_000.0,
            420.0,
        )
        for offset in range(20)
    ) + (
        metric_trends.NormalizedTrendSample(
            TARGET + timedelta(days=100),
            10_000.0,
            420.0,
        ),
    )

    default_decisions = metric_trends.analyze_trends(samples)
    explicit_decisions = metric_trends.analyze_trends(samples, as_of=TARGET)

    assert [decision.status for decision in default_decisions] == [
        metric_trends.TrendStatus.SPARSE,
        metric_trends.TrendStatus.SPARSE,
    ]
    assert [
        decision.statistics.month.sample_count for decision in default_decisions
    ] == [
        1,
        1,
    ]
    assert [decision.status for decision in explicit_decisions] == [
        metric_trends.TrendStatus.READY,
        metric_trends.TrendStatus.READY,
    ]


def test_no_data_sparse_and_unavailable_average_are_typed_separately() -> None:
    no_data = metric_trends.decide_metric_trend(
        metric_trends.STEPS,
        _statistics(
            filtered_count=0,
            week_count=0,
            week_average=None,
            month_count=0,
            month_average=None,
        ),
    )
    sparse_month = metric_trends.decide_metric_trend(
        metric_trends.STEPS,
        _statistics(filtered_count=30, week_count=3, month_count=19),
    )
    sparse_fallback = metric_trends.decide_metric_trend(
        metric_trends.STEPS,
        _statistics(
            filtered_count=8,
            week_count=0,
            week_average=None,
            month_count=0,
            month_average=None,
        ),
    )
    unavailable = metric_trends.decide_metric_trend(
        metric_trends.STEPS,
        _statistics(week_average=None),
    )

    assert no_data.status is metric_trends.TrendStatus.NO_DATA
    assert sparse_month.status is metric_trends.TrendStatus.SPARSE
    assert sparse_month.logged_sample_count == 19
    assert sparse_fallback.logged_sample_count == 8
    assert unavailable.status is metric_trends.TrendStatus.AVERAGE_UNAVAILABLE


@pytest.mark.parametrize(
    ("definition", "delta", "expected"),
    [
        (metric_trends.STEPS, 399.999, metric_trends.TrendDirection.STEADY),
        (metric_trends.STEPS, 400.0, metric_trends.TrendDirection.UP),
        (metric_trends.STEPS, 400.001, metric_trends.TrendDirection.UP),
        (metric_trends.STEPS, -399.999, metric_trends.TrendDirection.STEADY),
        (metric_trends.STEPS, -400.0, metric_trends.TrendDirection.DOWN),
        (metric_trends.STEPS, -400.001, metric_trends.TrendDirection.DOWN),
        (metric_trends.SLEEP, 5.999, metric_trends.TrendDirection.STEADY),
        (metric_trends.SLEEP, 6.0, metric_trends.TrendDirection.UP),
        (metric_trends.SLEEP, 6.001, metric_trends.TrendDirection.UP),
        (metric_trends.SLEEP, -5.999, metric_trends.TrendDirection.STEADY),
        (metric_trends.SLEEP, -6.0, metric_trends.TrendDirection.DOWN),
        (metric_trends.SLEEP, -6.001, metric_trends.TrendDirection.DOWN),
    ],
)
def test_current_decision_thresholds_are_inclusive(
    definition: metric_trends.MetricDefinition,
    delta: float,
    expected: metric_trends.TrendDirection,
) -> None:
    decision = _decision(
        definition,
        week_average=10_000.0 + delta,
        month_average=10_000.0,
    )

    assert decision.status is metric_trends.TrendStatus.READY
    assert decision.current_delta == pytest.approx(delta)
    assert decision.current_direction is expected


def test_non_finite_nan_delta_preserves_the_legacy_steady_decision() -> None:
    assert (
        metric_trends.classify_direction(nan, metric_trends.STEPS.significance)
        is metric_trends.TrendDirection.STEADY
    )


@pytest.mark.parametrize(
    ("definition", "baseline_delta", "expected"),
    [
        (metric_trends.STEPS, 199.999, metric_trends.BaselineState.STEADY),
        (metric_trends.STEPS, 200.0, metric_trends.BaselineState.UP),
        (metric_trends.STEPS, 200.001, metric_trends.BaselineState.UP),
        (metric_trends.STEPS, -199.999, metric_trends.BaselineState.STEADY),
        (metric_trends.STEPS, -200.0, metric_trends.BaselineState.DOWN),
        (metric_trends.STEPS, -200.001, metric_trends.BaselineState.DOWN),
        (metric_trends.SLEEP, 2.999, metric_trends.BaselineState.STEADY),
        (metric_trends.SLEEP, 3.0, metric_trends.BaselineState.UP),
        (metric_trends.SLEEP, 3.001, metric_trends.BaselineState.UP),
        (metric_trends.SLEEP, -2.999, metric_trends.BaselineState.STEADY),
        (metric_trends.SLEEP, -3.0, metric_trends.BaselineState.DOWN),
        (metric_trends.SLEEP, -3.001, metric_trends.BaselineState.DOWN),
    ],
)
def test_baseline_half_thresholds_are_inclusive(
    definition: metric_trends.MetricDefinition,
    baseline_delta: float,
    expected: metric_trends.BaselineState,
) -> None:
    month_average = 10_000.0
    decision = _decision(
        definition,
        month_average=month_average,
        baseline_count=21,
        baseline_average=month_average - baseline_delta,
    )

    assert decision.baseline_delta == pytest.approx(baseline_delta)
    assert decision.baseline_state is expected


def test_baseline_absent_forming_and_unavailable_average_states() -> None:
    absent = _decision(metric_trends.STEPS)
    forming = _decision(
        metric_trends.STEPS,
        baseline_count=20,
        baseline_average=9_000.0,
    )
    unavailable = _decision(
        metric_trends.STEPS,
        baseline_count=21,
        baseline_average=None,
    )

    assert absent.baseline_state is metric_trends.BaselineState.FORMING
    assert forming.baseline_state is metric_trends.BaselineState.FORMING
    assert unavailable.baseline_state is metric_trends.BaselineState.FORMING
    assert absent.baseline_average is None
    assert forming.baseline_average is None
    assert unavailable.baseline_average is None


def test_metric_formatters_preserve_rounding_and_units() -> None:
    assert (
        metric_trends.format_metric_value(metric_trends.TrendMetric.STEPS, 12_345.6)
        == "12,346 steps/day"
    )
    assert (
        metric_trends.format_metric_delta(metric_trends.TrendMetric.STEPS, 399.6)
        == "400 steps"
    )
    assert (
        metric_trends.format_metric_value(metric_trends.TrendMetric.SLEEP, 425.0)
        == "7.1 h/night"
    )
    assert (
        metric_trends.format_metric_delta(metric_trends.TrendMetric.SLEEP, 6.0)
        == "0.1 h"
    )


def test_renderer_handles_each_availability_state_exactly() -> None:
    no_data = metric_trends.decide_metric_trend(
        metric_trends.STEPS,
        _statistics(
            filtered_count=0,
            week_count=0,
            week_average=None,
            month_count=0,
            month_average=None,
        ),
    )
    sparse = metric_trends.decide_metric_trend(
        metric_trends.SLEEP,
        _statistics(filtered_count=12, week_count=3, month_count=12),
    )
    unavailable = metric_trends.decide_metric_trend(
        metric_trends.STEPS,
        _statistics(month_average=None),
    )

    assert metric_trends.render_metric_trend(no_data) == (
        "Steps trend: no data logged yet."
    )
    assert metric_trends.render_metric_trend(sparse) == (
        "Sleep trend: need more data logged (only 12 days in last 30d)."
    )
    assert metric_trends.render_metric_trend(unavailable) == (
        "Steps trend: need more data logged."
    )


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (
            _decision(metric_trends.STEPS),
            "Steps trend: 10,000 steps/day (steady vs 30d avg 10,000 steps/day; "
            "60d base still forming).",
        ),
        (
            _decision(
                metric_trends.STEPS,
                week_average=10_400.0,
                baseline_count=21,
                baseline_average=10_000.0,
            ),
            "Steps trend: 10,400 steps/day (up 400 steps vs 30d avg 10,000 steps/day; "
            "60d base 10,000 steps/day).",
        ),
        (
            _decision(
                metric_trends.STEPS,
                week_average=9_600.0,
                baseline_count=21,
                baseline_average=9_800.0,
            ),
            "Steps trend: 9,600 steps/day (down 400 steps vs 30d avg 10,000 steps/day; "
            "up 200 steps vs 60d base 9,800 steps/day).",
        ),
        (
            _decision(
                metric_trends.SLEEP,
                week_average=414.0,
                month_average=420.0,
                baseline_count=21,
                baseline_average=423.0,
            ),
            "Sleep trend: 6.9 h/night (down 0.1 h vs 30d avg 7.0 h/night; "
            "down 0.1 h vs 60d base 7.0 h/night).",
        ),
    ],
)
def test_renderer_uses_typed_directions_for_exact_prose(
    decision: metric_trends.MetricTrendDecision,
    expected: str,
) -> None:
    assert metric_trends.render_metric_trend(decision) == expected


def test_renderer_defensive_helpers_preserve_fallbacks_for_incomplete_decisions() -> (
    None
):
    missing_current = metric_trends.MetricTrendDecision(
        definition=metric_trends.STEPS,
        status=metric_trends.TrendStatus.READY,
        statistics=_statistics(month_average=None),
        current_direction=None,
        current_delta=None,
        baseline_state=metric_trends.BaselineState.FORMING,
    )
    missing_baseline = metric_trends.MetricTrendDecision(
        definition=metric_trends.STEPS,
        status=metric_trends.TrendStatus.READY,
        statistics=_statistics(),
        current_direction=metric_trends.TrendDirection.STEADY,
        current_delta=0.0,
        baseline_state=metric_trends.BaselineState.UP,
    )

    assert metric_trends._render_current_comparison(missing_current) == ""
    assert (
        metric_trends._render_baseline_comparison(missing_baseline)
        == "60d base still forming"
    )


def test_line_renderer_normalizes_every_line_before_python_slicing() -> None:
    decisions = (
        metric_trends.decide_metric_trend(
            metric_trends.STEPS,
            _statistics(
                filtered_count=0,
                week_count=0,
                week_average=None,
                month_count=0,
                month_average=None,
            ),
        ),
        metric_trends.decide_metric_trend(
            metric_trends.SLEEP,
            _statistics(
                filtered_count=0,
                week_count=0,
                week_average=None,
                month_count=0,
                month_average=None,
            ),
        ),
    )
    normalized: list[str] = []

    def normalize_sentence(text: str) -> str:
        normalized.append(text)
        return formatters.ensure_sentence(text)

    assert metric_trends.render_trend_lines(
        decisions,
        normalize_sentence=normalize_sentence,
        limit=-1,
    ) == ["Steps trend: no data logged yet."]
    assert normalized == [
        "Steps trend: no data logged yet.",
        "Sleep trend: no data logged yet.",
    ]


def test_boundary_compute_returns_empty_without_invoking_sentence_rendering() -> None:
    rendered: list[str] = []

    assert (
        metric_trends.compute_trend_lines(
            [],
            parse_date=converters.to_date,
            normalize_sentence=lambda text: rendered.append(text) or text,
        )
        == []
    )
    assert rendered == []


def test_boundary_preserves_falsey_sequence_short_circuit() -> None:
    class _FalseySamples:
        def __bool__(self) -> bool:
            return False

        def __iter__(self):
            raise AssertionError("falsey input must not be iterated")

    assert (
        metric_trends.compute_trend_lines(
            cast(Any, _FalseySamples()),
            parse_date=converters.to_date,
            normalize_sentence=formatters.ensure_sentence,
        )
        == []
    )
