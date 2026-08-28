"""Typed normalization, policy, analysis, and rendering for Steps/Sleep trends."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Callable, Final


DateParser = Callable[[object], date | None]
SentenceNormalizer = Callable[[str], str]


class TrendMetric(Enum):
    """The two metrics supported by the established trend contract."""

    STEPS = "Steps"
    SLEEP = "Sleep"


class TrendStatus(Enum):
    """Availability of a metric decision for prose rendering."""

    NO_DATA = "no_data"
    SPARSE = "sparse"
    AVERAGE_UNAVAILABLE = "average_unavailable"
    READY = "ready"


class TrendDirection(Enum):
    """Direction of a significant current-window comparison."""

    UP = "up"
    DOWN = "down"
    STEADY = "steady"


class BaselineState(Enum):
    """Availability and direction of the 60-day baseline comparison."""

    FORMING = "forming"
    UP = "up"
    DOWN = "down"
    STEADY = "steady"


@dataclass(frozen=True)
class MetricDefinition:
    """Immutable schema and threshold policy for one trend metric."""

    metric: TrendMetric
    paths: tuple[tuple[str, ...], ...]
    significance: float
    min_week_samples: int = 4
    min_month_samples: int = 20
    min_baseline_samples: int = 21
    include_zero: bool = False


@dataclass(frozen=True)
class NormalizedTrendSample:
    """One accepted row with both metric values resolved by precedence."""

    day: date
    steps: float | None
    sleep_minutes: float | None


@dataclass(frozen=True)
class WindowStatistic:
    """Count and arithmetic mean for one inclusive time window."""

    sample_count: int
    average: float | None


@dataclass(frozen=True)
class TrendWindowStatistics:
    """All statistics needed to make one metric decision."""

    filtered_sample_count: int
    week: WindowStatistic
    month: WindowStatistic
    baseline: WindowStatistic


@dataclass(frozen=True)
class MetricTrendDecision:
    """Typed calculation outcome consumed by the prose renderer."""

    definition: MetricDefinition
    status: TrendStatus
    statistics: TrendWindowStatistics
    logged_sample_count: int = 0
    current_direction: TrendDirection | None = None
    current_delta: float | None = None
    baseline_state: BaselineState | None = None
    baseline_average: float | None = None
    baseline_delta: float | None = None


STEPS: Final = MetricDefinition(
    metric=TrendMetric.STEPS,
    paths=(("activity", "steps"), ("steps",)),
    significance=400.0,
)
SLEEP: Final = MetricDefinition(
    metric=TrendMetric.SLEEP,
    paths=(("sleep", "asleep_minutes"), ("sleep_asleep_minutes",)),
    significance=6.0,
)
METRIC_DEFINITIONS: Final = (STEPS, SLEEP)


def _normalize_date(value: object, parse_date: DateParser) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return parse_date(value)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _value_at_path(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def resolve_metric_value(
    payload: Mapping[str, Any],
    definition: MetricDefinition,
) -> float | None:
    """Return the first convertible and eligible value in path order."""

    for path in definition.paths:
        raw_value = _value_at_path(payload, path)
        if raw_value is None:
            continue
        value = _to_float(raw_value)
        if value is None:
            continue
        if value <= 0 and not definition.include_zero:
            continue
        return value
    return None


def normalize_sample(
    sample_date: object,
    payload: object,
    *,
    parse_date: DateParser,
) -> NormalizedTrendSample | None:
    """Normalize one raw pair, retaining rows even when both metrics are absent."""

    day = _normalize_date(sample_date, parse_date)
    if day is None or not isinstance(payload, Mapping):
        return None
    return NormalizedTrendSample(
        day=day,
        steps=resolve_metric_value(payload, STEPS),
        sleep_minutes=resolve_metric_value(payload, SLEEP),
    )


def normalize_samples(
    samples: Sequence[tuple[date | datetime, Mapping[str, Any]]],
    *,
    parse_date: DateParser,
) -> tuple[NormalizedTrendSample, ...]:
    """Normalize and stably sort accepted rows without deduplicating dates."""

    normalized: list[NormalizedTrendSample] = []
    for sample_date, payload in samples:
        sample = normalize_sample(sample_date, payload, parse_date=parse_date)
        if sample is not None:
            normalized.append(sample)
    normalized.sort(key=lambda sample: sample.day)
    return tuple(normalized)


def metric_sample_value(
    sample: NormalizedTrendSample,
    metric: TrendMetric,
) -> float | None:
    """Select a normalized value without returning to raw dictionary paths."""

    if metric is TrendMetric.STEPS:
        return sample.steps
    return sample.sleep_minutes


def mean_value(values: Sequence[float]) -> float | None:
    """Return the established arithmetic mean, or ``None`` for no values."""

    if not values:
        return None
    return sum(values) / len(values)


def _window_statistic(values: Sequence[float]) -> WindowStatistic:
    return WindowStatistic(sample_count=len(values), average=mean_value(values))


def calculate_window_statistics(
    definition: MetricDefinition,
    samples: Sequence[NormalizedTrendSample],
    target_day: date,
) -> TrendWindowStatistics:
    """Calculate the inclusive 7d, 30d, and preceding 60d windows."""

    filtered = tuple(
        (sample.day, value)
        for sample in samples
        if sample.day <= target_day
        if (value := metric_sample_value(sample, definition.metric)) is not None
    )
    week_start = target_day - timedelta(days=6)
    month_start = target_day - timedelta(days=29)
    baseline_start = target_day - timedelta(days=89)
    baseline_end = month_start - timedelta(days=1)
    week_values = tuple(
        value for day, value in filtered if week_start <= day <= target_day
    )
    month_values = tuple(
        value for day, value in filtered if month_start <= day <= target_day
    )
    baseline_values = tuple(
        value for day, value in filtered if baseline_start <= day <= baseline_end
    )
    return TrendWindowStatistics(
        filtered_sample_count=len(filtered),
        week=_window_statistic(week_values),
        month=_window_statistic(month_values),
        baseline=_window_statistic(baseline_values),
    )


def classify_direction(delta: float, significance: float) -> TrendDirection:
    """Apply the inclusive significance threshold to a signed delta."""

    if abs(delta) >= significance:
        if delta > 0:
            return TrendDirection.UP
        return TrendDirection.DOWN
    return TrendDirection.STEADY


def _baseline_decision(
    definition: MetricDefinition,
    statistics: TrendWindowStatistics,
    month_average: float,
) -> tuple[BaselineState, float | None, float | None]:
    baseline_average = statistics.baseline.average
    if (
        statistics.baseline.sample_count < definition.min_baseline_samples
        or baseline_average is None
    ):
        return BaselineState.FORMING, None, None
    delta = month_average - baseline_average
    direction = classify_direction(delta, definition.significance / 2)
    return BaselineState(direction.value), baseline_average, delta


def decide_metric_trend(
    definition: MetricDefinition,
    statistics: TrendWindowStatistics,
) -> MetricTrendDecision:
    """Apply sample minima and significance policy to window statistics."""

    if statistics.filtered_sample_count == 0:
        return MetricTrendDecision(definition, TrendStatus.NO_DATA, statistics)
    if (
        statistics.week.sample_count < definition.min_week_samples
        or statistics.month.sample_count < definition.min_month_samples
    ):
        logged = statistics.month.sample_count or statistics.filtered_sample_count
        return MetricTrendDecision(
            definition,
            TrendStatus.SPARSE,
            statistics,
            logged_sample_count=logged,
        )
    week_average = statistics.week.average
    month_average = statistics.month.average
    if week_average is None or month_average is None:
        return MetricTrendDecision(
            definition,
            TrendStatus.AVERAGE_UNAVAILABLE,
            statistics,
        )
    current_delta = week_average - month_average
    current_direction = classify_direction(current_delta, definition.significance)
    baseline_state, baseline_average, baseline_delta = _baseline_decision(
        definition,
        statistics,
        month_average,
    )
    return MetricTrendDecision(
        definition,
        TrendStatus.READY,
        statistics,
        current_direction=current_direction,
        current_delta=current_delta,
        baseline_state=baseline_state,
        baseline_average=baseline_average,
        baseline_delta=baseline_delta,
    )


def analyze_metric_trend(
    definition: MetricDefinition,
    samples: Sequence[NormalizedTrendSample],
    target_day: date,
) -> MetricTrendDecision:
    """Calculate and decide one metric trend without rendering prose."""

    statistics = calculate_window_statistics(definition, samples, target_day)
    return decide_metric_trend(definition, statistics)


def analyze_trends(
    samples: Sequence[NormalizedTrendSample],
    *,
    as_of: date | None = None,
) -> tuple[MetricTrendDecision, ...]:
    """Analyze Steps then Sleep, using the latest normalized date by default."""

    if not samples:
        return ()
    target_day = as_of or samples[-1].day
    return tuple(
        analyze_metric_trend(definition, samples, target_day)
        for definition in METRIC_DEFINITIONS
    )


def format_metric_value(metric: TrendMetric, value: float) -> str:
    """Format one average using the exact established metric units."""

    if metric is TrendMetric.STEPS:
        return f"{value:,.0f} steps/day"
    return f"{value / 60.0:.1f} h/night"


def format_metric_delta(metric: TrendMetric, value: float) -> str:
    """Format one absolute delta using the exact established metric units."""

    if metric is TrendMetric.STEPS:
        return f"{value:,.0f} steps"
    return f"{value / 60.0:.1f} h"


def _render_current_comparison(decision: MetricTrendDecision) -> str:
    metric = decision.definition.metric
    month_average = decision.statistics.month.average
    delta = decision.current_delta
    if month_average is None or delta is None:
        return ""
    month_text = format_metric_value(metric, month_average)
    if decision.current_direction is TrendDirection.STEADY:
        return f"steady vs 30d avg {month_text}"
    direction = decision.current_direction or TrendDirection.DOWN
    return (
        f"{direction.value} {format_metric_delta(metric, abs(delta))} "
        f"vs 30d avg {month_text}"
    )


def _render_baseline_comparison(decision: MetricTrendDecision) -> str:
    if decision.baseline_state is BaselineState.FORMING:
        return "60d base still forming"
    metric = decision.definition.metric
    baseline_average = decision.baseline_average
    delta = decision.baseline_delta
    if baseline_average is None or delta is None:
        return "60d base still forming"
    baseline_text = format_metric_value(metric, baseline_average)
    if decision.baseline_state is BaselineState.STEADY:
        return f"60d base {baseline_text}"
    direction = decision.baseline_state or BaselineState.DOWN
    return (
        f"{direction.value} {format_metric_delta(metric, abs(delta))} "
        f"vs 60d base {baseline_text}"
    )


def render_metric_trend(decision: MetricTrendDecision) -> str:
    """Render one typed decision using the exact compatibility prose."""

    name = decision.definition.metric.value
    if decision.status is TrendStatus.NO_DATA:
        return f"{name} trend: no data logged yet."
    if decision.status is TrendStatus.SPARSE:
        return (
            f"{name} trend: need more data logged "
            f"(only {decision.logged_sample_count} days in last 30d)."
        )
    week_average = decision.statistics.week.average
    if decision.status is not TrendStatus.READY or week_average is None:
        return f"{name} trend: need more data logged."
    week_text = format_metric_value(decision.definition.metric, week_average)
    current = _render_current_comparison(decision)
    baseline = _render_baseline_comparison(decision)
    return f"{name} trend: {week_text} ({current}; {baseline})."


def render_trend_lines(
    decisions: Sequence[MetricTrendDecision],
    *,
    normalize_sentence: SentenceNormalizer,
    limit: int | None = None,
) -> list[str]:
    """Render and sentence-normalize every line before optional slicing."""

    lines = [
        normalize_sentence(render_metric_trend(decision)) for decision in decisions
    ]
    if limit is not None:
        lines = lines[:limit]
    return lines


def compute_trend_lines(
    samples: Sequence[tuple[date | datetime, Mapping[str, Any]]],
    *,
    as_of: date | None = None,
    limit: int | None = None,
    parse_date: DateParser,
    normalize_sentence: SentenceNormalizer,
) -> list[str]:
    """Normalize, analyze, and render the stable Steps/Sleep trend contract."""

    if not samples:
        return []
    normalized = normalize_samples(samples, parse_date=parse_date)
    if not normalized:
        return []
    decisions = analyze_trends(normalized, as_of=as_of)
    return render_trend_lines(
        decisions,
        normalize_sentence=normalize_sentence,
        limit=limit,
    )
