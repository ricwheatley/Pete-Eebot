"""Application-owned daily-summary construction and supplemental analysis."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol, cast

from pete_e.domain import metric_trends
from pete_e.domain.body_age_history import (
    BodyAgeHistoryReader,
    LegacyBodyAgeHistoryReader,
)
from pete_e.domain.body_age_trend import BodyAgeTrend, analyze_body_age_trend


WarningSink = Callable[[str], None]
BodyAgeTrendLoader = Callable[[object, date], object | None]
TodayProvider = Callable[[], date]


class DailySummaryMessageBuilder(Protocol):
    """Build the authoritative user-visible summary for an optional date."""

    def build_daily_summary_message(self, target_date: date | None = None) -> str: ...


class DailySummaryRenderProfile(Enum):
    """Named compatibility policies for the two established summary paths."""

    PRODUCTION = "production"
    LEGACY_CLI = "legacy_cli"


class SupplementalDirection(Enum):
    """Direction labels shared by muscle and HRV analysis."""

    UP = "up"
    DOWN = "down"
    STEADY = "steady"


@dataclass(frozen=True)
class BodyCompositionTrend:
    """Rounded current/prior muscle averages and their decided direction."""

    current_average: float
    previous_average: float | None
    difference: float | None
    direction: SupplementalDirection | None


@dataclass(frozen=True)
class HrvTrend:
    """Selected HRV sample and its comparison with earlier window samples."""

    sample_date: date
    current_value: float
    previous_average: float | None
    direction: SupplementalDirection


@dataclass(frozen=True)
class _HistoryLoad:
    available: bool
    rows: object = None


@dataclass(frozen=True)
class _LoaderResolution:
    available: bool
    loader: object = None


HRV_METRIC_KEYS = ("hrv_sdnn_ms", "hrv_rmssd_ms", "hrv_daily_ms", "hrv")


def _ignore_warning(message: str) -> None:
    del message


def coerce_summary_date(value: object) -> date | None:
    """Preserve the legacy date-before-datetime coercion order."""

    if isinstance(value, date):
        return value
    if isinstance(value, datetime):  # pragma: no cover - shadowed compatibility branch
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _legacy_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _production_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return cast(float, value)


def _metric_number(
    value: object,
    profile: DailySummaryRenderProfile,
) -> float | None:
    if profile is DailySummaryRenderProfile.LEGACY_CLI:
        return _legacy_number(value)
    return _production_number(value)


def _body_composition_rows(
    raw_rows: object,
    profile: DailySummaryRenderProfile,
) -> Iterable[dict[str, object]]:
    if profile is DailySummaryRenderProfile.LEGACY_CLI:
        return cast(Iterable[dict[str, object]], raw_rows)
    if not raw_rows:
        return ()
    return (
        cast(dict[str, object], row)
        for row in cast(Iterable[object], raw_rows)
        if isinstance(row, dict)
    )


def _hrv_rows(raw_rows: object) -> Iterable[dict[str, object]]:
    if not raw_rows:
        return ()
    return (
        cast(dict[str, object], row)
        for row in cast(Iterable[object], raw_rows)
        if isinstance(row, dict)
    )


def _body_composition_samples(
    raw_rows: object,
    target_date: date,
    profile: DailySummaryRenderProfile,
) -> list[tuple[date, float]]:
    window_start = target_date - timedelta(days=13)
    samples: list[tuple[date, float]] = []
    for row in _body_composition_rows(raw_rows, profile):
        row_date = coerce_summary_date(row.get("date"))
        if row_date is None or row_date > target_date or row_date < window_start:
            continue
        muscle_pct = _metric_number(row.get("muscle_pct"), profile)
        if muscle_pct is not None:
            samples.append((row_date, muscle_pct))
    samples.sort(key=lambda item: item[0])
    return samples


def _muscle_direction(difference: float) -> SupplementalDirection:
    if abs(difference) < 0.5:
        return SupplementalDirection.STEADY
    if difference > 0:
        return SupplementalDirection.UP
    return SupplementalDirection.DOWN


def analyze_body_composition(
    raw_rows: object,
    target_date: date,
    profile: DailySummaryRenderProfile,
) -> BodyCompositionTrend | None:
    """Apply the established two seven-day windows and sample minimums."""

    samples = _body_composition_samples(raw_rows, target_date, profile)
    if not samples:
        return None
    current_start = target_date - timedelta(days=6)
    window_start = target_date - timedelta(days=13)
    current = [value for day, value in samples if current_start <= day <= target_date]
    previous = [value for day, value in samples if window_start <= day < current_start]
    if len(current) < 3:
        return None
    current_average = round(sum(current) / len(current), 1)
    if len(previous) < 3:
        return BodyCompositionTrend(current_average, None, None, None)
    previous_average = round(sum(previous) / len(previous), 1)
    difference = round(current_average - previous_average, 1)
    return BodyCompositionTrend(
        current_average,
        previous_average,
        difference,
        _muscle_direction(difference),
    )


def render_body_composition(trend: BodyCompositionTrend | None) -> str | None:
    """Render the profile-independent muscle wording."""

    if trend is None:
        return None
    line = f"Muscle trend: {trend.current_average:.1f}% avg this week"
    if trend.previous_average is None or trend.difference is None:
        return f"{line}."
    if trend.direction is SupplementalDirection.STEADY:
        return f"{line} (steady vs prior)."
    direction = trend.direction or SupplementalDirection.DOWN
    return f"{line} ({direction.value} {abs(trend.difference):.1f}% vs prior)."


def _first_hrv_value(
    row: Mapping[str, object],
    profile: DailySummaryRenderProfile,
) -> float | None:
    for key in HRV_METRIC_KEYS:
        value = _metric_number(row.get(key), profile)
        if value is not None:
            return value
    return None


def _hrv_samples(
    raw_rows: object,
    target_date: date,
    profile: DailySummaryRenderProfile,
) -> list[tuple[date, float]]:
    window_start = target_date - timedelta(days=6)
    samples: list[tuple[date, float]] = []
    for row in _hrv_rows(raw_rows):
        row_date = coerce_summary_date(row.get("date"))
        if row_date is None or row_date < window_start or row_date > target_date:
            continue
        hrv_value = _first_hrv_value(row, profile)
        if hrv_value is not None and hrv_value > 0:
            samples.append((row_date, hrv_value))
    samples.sort(key=lambda item: item[0])
    return samples


def _hrv_direction(
    current_value: float,
    previous_average: float | None,
) -> SupplementalDirection:
    if previous_average is None:
        return SupplementalDirection.STEADY
    difference = current_value - previous_average
    if difference >= 2.0:
        return SupplementalDirection.UP
    if difference <= -2.0:
        return SupplementalDirection.DOWN
    return SupplementalDirection.STEADY


def analyze_hrv(
    raw_rows: object,
    target_date: date,
    profile: DailySummaryRenderProfile,
) -> HrvTrend | None:
    """Select target/latest HRV and compare it with earlier seven-day samples."""

    samples = _hrv_samples(raw_rows, target_date, profile)
    if not samples:
        return None
    sample_date = target_date
    current_value = next(
        (value for day, value in samples if day == target_date),
        None,
    )
    if current_value is None:
        sample_date, current_value = samples[-1]
    previous = [value for day, value in samples if day < sample_date]
    previous_average = sum(previous) / len(previous) if previous else None
    return HrvTrend(
        sample_date,
        current_value,
        previous_average,
        _hrv_direction(current_value, previous_average),
    )


def render_hrv(
    trend: HrvTrend | None,
    profile: DailySummaryRenderProfile,
) -> str | None:
    """Render the explicit production or arrow-based legacy HRV profile."""

    if trend is None:
        return None
    if profile is DailySummaryRenderProfile.LEGACY_CLI:
        arrows = {
            SupplementalDirection.UP: "↗",
            SupplementalDirection.DOWN: "↘",
            SupplementalDirection.STEADY: "→",
        }
        line = f"HRV: {trend.current_value:.0f} ms {arrows[trend.direction]}"
        if trend.previous_average is not None:
            line += f" (7d avg {trend.previous_average:.0f} ms)"
        return line
    line = f"HRV: {trend.current_value:.0f} ms ({trend.direction.value})"
    if trend.previous_average is not None:
        line += f" vs 7d avg {trend.previous_average:.0f} ms"
    return line


def render_body_age(
    trend: object | None,
    profile: DailySummaryRenderProfile,
) -> str | None:
    """Render Body Age while retaining the legacy missing-value line."""

    if trend is None:
        return None
    value = getattr(trend, "value", None)
    delta = getattr(trend, "delta", None)
    if value is None:
        if profile is DailySummaryRenderProfile.LEGACY_CLI:
            return "Body Age: n/a"
        return None
    line = f"Body Age: {value:.1f}y"
    if delta is None:
        return f"{line} (7d delta n/a)"
    return f"{line} (7d delta {delta:+.1f}y)"


def load_body_age_trend(source: object, target_date: date) -> BodyAgeTrend:
    """Read and analyze Body Age through the completed typed domain boundary."""

    start_date = target_date - timedelta(days=7)
    reader: BodyAgeHistoryReader = LegacyBodyAgeHistoryReader(source)
    return analyze_body_age_trend(
        reader.read_body_age_history(start_date, target_date),
        target_date,
    )


def _resolve_loader(
    source: object,
    name: str,
    profile: DailySummaryRenderProfile,
) -> _LoaderResolution:
    if profile is DailySummaryRenderProfile.LEGACY_CLI:
        if not hasattr(source, name):
            return _LoaderResolution(False)
        return _LoaderResolution(True, getattr(source, name))
    loader = getattr(source, name, None)
    if not callable(loader):
        return _LoaderResolution(False)
    return _LoaderResolution(True, loader)


def _history_error_message(
    label: str,
    profile: DailySummaryRenderProfile,
    error: Exception,
) -> str:
    context = (
        " for voice context" if profile is DailySummaryRenderProfile.PRODUCTION else ""
    )
    return f"Failed to load {label} history{context}: {error}"


def _load_history(
    source: object,
    name: str,
    arguments: Sequence[object],
    *,
    label: str,
    profile: DailySummaryRenderProfile,
    warning_sink: WarningSink,
) -> _HistoryLoad:
    resolution = _resolve_loader(source, name, profile)
    if not resolution.available:
        return _HistoryLoad(False)
    try:
        loader = cast(Callable[..., object], resolution.loader)
        return _HistoryLoad(True, loader(*arguments))
    except Exception as error:
        warning_sink(_history_error_message(label, profile, error))
        return _HistoryLoad(False)


def collect_trend_samples(
    source: object,
    target_date: date,
    profile: DailySummaryRenderProfile,
    warning_sink: WarningSink = _ignore_warning,
) -> list[tuple[date, dict[str, Any]]]:
    """Load, filter, and sort raw rows for the typed metric-trend boundary."""

    start_date = target_date - timedelta(days=89)
    loaded = _load_history(
        source,
        "get_historical_data",
        (start_date, target_date),
        label="trend",
        profile=profile,
        warning_sink=warning_sink,
    )
    if not loaded.available:
        return []
    samples: list[tuple[date, dict[str, Any]]] = []
    for row in cast(Iterable[object], loaded.rows or []):
        if not isinstance(row, dict):
            continue
        row_date = coerce_summary_date(row.get("date"))
        if row_date is None or row_date > target_date:
            continue
        samples.append((row_date, cast(dict[str, Any], row)))
    samples.sort(key=lambda item: item[0])
    return samples


def build_trend_paragraph(
    samples: Sequence[tuple[date, Mapping[str, Any]]],
    target_date: date,
) -> str | None:
    """Analyze and render Steps/Sleep in their established paragraph order."""

    if not samples:
        return None
    lines = metric_trends.compute_trend_lines(
        samples,
        as_of=target_date,
        limit=2,
        parse_date=_to_trend_date,
        normalize_sentence=_ensure_trend_sentence,
    )
    if not lines:
        return None
    return " ".join(["Trend check: " + lines[0], *lines[1:]])


def _to_trend_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _ensure_trend_sentence(text: str) -> str:
    body = text.strip()
    if not body or body[-1] in ".!?":
        return body
    return f"{body}."


def append_summary_line(base: str | None, addition: str) -> str:
    """Append one supplemental line with the established newline behavior."""

    base_text = "" if base is None else str(base)
    if not addition:
        return base_text
    if not base_text:
        return addition
    if not base_text.endswith("\n"):
        base_text = f"{base_text}\n"
    return f"{base_text}{addition}"


def append_summary_lines(base: str | None, additions: Iterable[str]) -> str:
    """Append ordered non-empty supplemental lines."""

    result = "" if base is None else str(base)
    for addition in additions:
        result = append_summary_line(result, addition)
    return result


class DailySummarySupplementalBuilder:
    """Load histories, invoke pure analyzers, and render one named profile."""

    def __init__(
        self,
        source: object,
        *,
        profile: DailySummaryRenderProfile,
        warning_sink: WarningSink = _ignore_warning,
        body_age_loader: BodyAgeTrendLoader = load_body_age_trend,
    ) -> None:
        self._source = source
        self._profile = profile
        self._warning_sink = warning_sink
        self._body_age_loader = body_age_loader

    def format_body_age_line(self, target_date: date) -> str | None:
        try:
            trend = self._body_age_loader(self._source, target_date)
        except Exception as error:
            if self._profile is DailySummaryRenderProfile.LEGACY_CLI:
                raise
            self._warning_sink(
                f"Failed to load body age trend for voice context: {error}"
            )
            return None
        return render_body_age(trend, self._profile)

    def format_body_composition_line(self, target_date: date) -> str | None:
        loaded = _load_history(
            self._source,
            "get_historical_metrics",
            (14,),
            label="body composition",
            profile=self._profile,
            warning_sink=self._warning_sink,
        )
        if not loaded.available:
            return None
        trend = analyze_body_composition(loaded.rows, target_date, self._profile)
        return render_body_composition(trend)

    def format_hrv_line(self, target_date: date) -> str | None:
        loaded = _load_history(
            self._source,
            "get_historical_metrics",
            (14,),
            label="HRV",
            profile=self._profile,
            warning_sink=self._warning_sink,
        )
        if not loaded.available:
            return None
        trend = analyze_hrv(loaded.rows, target_date, self._profile)
        return render_hrv(trend, self._profile)

    def build_trend_paragraph(self, target_date: date) -> str | None:
        samples = collect_trend_samples(
            self._source,
            target_date,
            self._profile,
            self._warning_sink,
        )
        return build_trend_paragraph(samples, target_date)

    def collect_trend_samples(
        self,
        target_date: date,
    ) -> list[tuple[date, dict[str, Any]]]:
        return collect_trend_samples(
            self._source,
            target_date,
            self._profile,
            self._warning_sink,
        )

    def build_lines(self, target_date: date) -> tuple[str, ...]:
        lines = (
            self.format_body_age_line(target_date),
            self.format_body_composition_line(target_date),
            self.format_hrv_line(target_date),
            self.build_trend_paragraph(target_date),
        )
        return tuple(line for line in lines if line)


class CompatibleDailySummaryMessageBuilder:
    """Preserve direct delegation and the duck-typed legacy fallback path."""

    def __init__(
        self,
        orchestrator: object,
        *,
        profile: DailySummaryRenderProfile = DailySummaryRenderProfile.LEGACY_CLI,
        warning_sink: WarningSink = _ignore_warning,
        body_age_loader: BodyAgeTrendLoader = load_body_age_trend,
        today: TodayProvider = date.today,
    ) -> None:
        self._orchestrator = orchestrator
        self._profile = profile
        self._warning_sink = warning_sink
        self._body_age_loader = body_age_loader
        self._today = today

    @staticmethod
    def _text(value: object) -> str:
        return "" if value is None else str(value)

    def build_daily_summary_message(self, target_date: date | None = None) -> str:
        authoritative = getattr(
            self._orchestrator,
            "build_daily_summary_message",
            None,
        )
        if callable(authoritative):
            return self._text(authoritative(target_date=target_date))
        fallback = getattr(self._orchestrator, "get_daily_summary")
        summary_text = self._text(fallback(target_date=target_date))
        source = getattr(self._orchestrator, "dal", None)
        if source is None:
            return summary_text
        target = target_date or (self._today() - timedelta(days=1))
        supplemental = DailySummarySupplementalBuilder(
            source,
            profile=self._profile,
            warning_sink=self._warning_sink,
            body_age_loader=self._body_age_loader,
        )
        return append_summary_lines(summary_text, supplemental.build_lines(target))


class FactoryDailySummaryMessageBuilder:
    """Resolve a composed builder lazily without any module-level service locator."""

    def __init__(self, factory: Callable[[], DailySummaryMessageBuilder]) -> None:
        self._factory = factory

    def build_daily_summary_message(self, target_date: date | None = None) -> str:
        return self._factory().build_daily_summary_message(target_date=target_date)


__all__ = [
    "BodyCompositionTrend",
    "CompatibleDailySummaryMessageBuilder",
    "DailySummaryMessageBuilder",
    "DailySummaryRenderProfile",
    "DailySummarySupplementalBuilder",
    "FactoryDailySummaryMessageBuilder",
    "HRV_METRIC_KEYS",
    "HrvTrend",
    "SupplementalDirection",
    "analyze_body_composition",
    "analyze_hrv",
    "append_summary_line",
    "append_summary_lines",
    "build_trend_paragraph",
    "coerce_summary_date",
    "collect_trend_samples",
    "load_body_age_trend",
    "render_body_age",
    "render_body_composition",
    "render_hrv",
]
