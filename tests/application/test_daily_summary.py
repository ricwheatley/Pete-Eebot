"""Direct unit tests for the typed daily-summary application boundary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from pete_e.application import daily_summary
from pete_e.application.daily_summary import (
    BodyCompositionTrend,
    CompatibleDailySummaryMessageBuilder,
    DailySummaryRenderProfile,
    DailySummarySupplementalBuilder,
    FactoryDailySummaryMessageBuilder,
    HrvTrend,
    SupplementalDirection,
    analyze_body_composition,
    analyze_hrv,
    append_summary_lines,
    build_trend_paragraph,
    coerce_summary_date,
    collect_trend_samples,
    render_body_composition,
    render_hrv,
)


TARGET = date(2026, 8, 23)
PRODUCTION = DailySummaryRenderProfile.PRODUCTION
LEGACY = DailySummaryRenderProfile.LEGACY_CLI


def test_typed_results_are_immutable() -> None:
    muscle = BodyCompositionTrend(42.0, 40.0, 2.0, SupplementalDirection.UP)
    hrv = HrvTrend(TARGET, 72.0, 70.0, SupplementalDirection.UP)

    with pytest.raises(FrozenInstanceError):
        muscle.current_average = 1.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        hrv.current_value = 1.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (TARGET, TARGET),
        ("2026-08-23", TARGET),
        ("invalid", None),
        (object(), None),
    ],
)
def test_summary_date_coercion(value: object, expected: date | None) -> None:
    assert coerce_summary_date(value) == expected


def test_summary_datetime_compatibility_returns_the_same_subclass_instance() -> None:
    value = datetime(2026, 8, 23, 10, 0)
    assert coerce_summary_date(value) is value


def test_production_decimal_body_composition_is_supported() -> None:
    rows = [
        {
            "date": TARGET - timedelta(days=offset),
            "muscle_pct": Decimal("42.0") if offset < 7 else Decimal("40.0"),
        }
        for offset in range(10)
    ]

    trend = analyze_body_composition(rows, TARGET, PRODUCTION)

    assert trend == BodyCompositionTrend(
        current_average=42.0,
        previous_average=40.0,
        difference=2.0,
        direction=SupplementalDirection.UP,
    )


def test_legacy_unconvertible_object_is_ignored() -> None:
    rows = [
        {"date": TARGET, "muscle_pct": object()},
        {"date": TARGET - timedelta(days=1), "muscle_pct": object()},
        {"date": TARGET - timedelta(days=2), "muscle_pct": object()},
    ]
    assert analyze_body_composition(rows, TARGET, LEGACY) is None


def test_body_composition_renderer_handles_explicit_fallback_direction() -> None:
    trend = BodyCompositionTrend(40.0, 41.0, -1.0, None)
    assert render_body_composition(trend) == (
        "Muscle trend: 40.0% avg this week (down 1.0% vs prior)."
    )


def test_hrv_empty_missing_and_no_previous_states() -> None:
    assert analyze_hrv(None, TARGET, PRODUCTION) is None
    assert analyze_hrv([{"date": TARGET}], TARGET, LEGACY) is None

    trend = analyze_hrv([{"date": TARGET, "hrv": 71}], TARGET, LEGACY)

    assert trend == HrvTrend(
        sample_date=TARGET,
        current_value=71.0,
        previous_average=None,
        direction=SupplementalDirection.STEADY,
    )
    assert render_hrv(trend, LEGACY) == "HRV: 71 ms →"
    assert render_hrv(trend, PRODUCTION) == "HRV: 71 ms (steady)"
    assert render_hrv(None, LEGACY) is None


def test_hrv_latest_sample_is_used_when_target_is_absent() -> None:
    trend = analyze_hrv(
        [
            {"date": TARGET - timedelta(days=2), "hrv": 60},
            {"date": TARGET - timedelta(days=1), "hrv": 64},
        ],
        TARGET,
        PRODUCTION,
    )

    assert trend == HrvTrend(
        sample_date=TARGET - timedelta(days=1),
        current_value=64,
        previous_average=60,
        direction=SupplementalDirection.UP,
    )


def test_collect_trend_samples_handles_absent_and_non_callable_loaders() -> None:
    assert collect_trend_samples(object(), TARGET, LEGACY) == []
    assert (
        collect_trend_samples(
            SimpleNamespace(get_historical_data=None),
            TARGET,
            PRODUCTION,
        )
        == []
    )


def test_default_warning_sink_suppresses_expected_loader_failure() -> None:
    class _Source:
        def get_historical_data(self, start: date, end: date):
            raise RuntimeError("offline")

    assert collect_trend_samples(_Source(), TARGET, PRODUCTION) == []


def test_legacy_non_callable_loader_warns_with_exact_message() -> None:
    warnings: list[str] = []
    builder = DailySummarySupplementalBuilder(
        SimpleNamespace(get_historical_metrics=None),
        profile=LEGACY,
        warning_sink=warnings.append,
    )

    assert builder.format_hrv_line(TARGET) is None
    assert warnings == ["Failed to load HRV history: 'NoneType' object is not callable"]


def test_trend_paragraph_empty_and_rendered_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert build_trend_paragraph([], TARGET) is None
    samples = [(TARGET, {"steps": 10_000})]
    monkeypatch.setattr(
        daily_summary.metric_trends,
        "compute_trend_lines",
        lambda *args, **kwargs: ["Steps line.", "Sleep line."],
    )

    assert build_trend_paragraph(samples, TARGET) == (
        "Trend check: Steps line. Sleep line."
    )


def test_trend_paragraph_handles_typed_renderer_returning_no_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        daily_summary.metric_trends,
        "compute_trend_lines",
        lambda *args, **kwargs: [],
    )
    assert build_trend_paragraph([(TARGET, {})], TARGET) is None


def test_trend_boundary_receives_legacy_conversion_and_sentence_policies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _exercise_collaborators(*args: object, **kwargs: object) -> list[str]:
        parse_date = kwargs["parse_date"]
        normalize_sentence = kwargs["normalize_sentence"]
        assert callable(parse_date)
        assert callable(normalize_sentence)
        assert parse_date(datetime(2026, 8, 23, 9, 30)) == TARGET
        assert parse_date(TARGET) == TARGET
        assert parse_date(None) is None
        assert parse_date(" ") is None
        assert parse_date("2026-08-23T09:30:00") == TARGET
        assert parse_date("invalid") is None
        assert normalize_sentence(" ") == ""
        assert normalize_sentence("Ready!") == "Ready!"
        assert normalize_sentence("Ready") == "Ready."
        return []

    monkeypatch.setattr(
        daily_summary.metric_trends,
        "compute_trend_lines",
        _exercise_collaborators,
    )

    assert build_trend_paragraph([(TARGET, {})], TARGET) is None


def test_body_age_loader_error_profiles_are_explicit() -> None:
    def _raise(source: object, target_date: date) -> object:
        raise RuntimeError("bad iterator")

    production_warnings: list[str] = []
    production = DailySummarySupplementalBuilder(
        object(),
        profile=PRODUCTION,
        warning_sink=production_warnings.append,
        body_age_loader=_raise,
    )
    legacy = DailySummarySupplementalBuilder(
        object(),
        profile=LEGACY,
        body_age_loader=_raise,
    )

    assert production.format_body_age_line(TARGET) is None
    assert production_warnings == [
        "Failed to load body age trend for voice context: bad iterator"
    ]
    with pytest.raises(RuntimeError, match="bad iterator"):
        legacy.format_body_age_line(TARGET)


def test_supplemental_builder_handles_unavailable_histories() -> None:
    builder = DailySummarySupplementalBuilder(
        object(),
        profile=PRODUCTION,
        body_age_loader=lambda source, target: None,
    )

    assert builder.build_lines(TARGET) == ()
    assert builder.format_body_composition_line(TARGET) is None
    assert builder.format_hrv_line(TARGET) is None
    assert builder.build_trend_paragraph(TARGET) is None
    assert builder.collect_trend_samples(TARGET) == []


def test_append_summary_lines_preserves_order_and_string_conversion() -> None:
    assert append_summary_lines(None, ["first", "second"]) == "first\nsecond"
    assert append_summary_lines("base\n", []) == "base\n"


@pytest.mark.parametrize(("value", "expected"), [(None, ""), (42, "42")])
def test_compatible_builder_coerces_authoritative_values(
    value: object,
    expected: str,
) -> None:
    orchestrator = SimpleNamespace(
        build_daily_summary_message=lambda target_date=None: value
    )
    builder = CompatibleDailySummaryMessageBuilder(orchestrator)
    assert builder.build_daily_summary_message(TARGET) == expected


def test_compatible_builder_uses_default_today_for_legacy_fallback() -> None:
    targets: list[date | None] = []
    source = object()
    orchestrator = SimpleNamespace(
        dal=source,
        get_daily_summary=lambda target_date=None: targets.append(target_date)
        or "base",
    )
    builder = CompatibleDailySummaryMessageBuilder(
        orchestrator,
        today=lambda: TARGET + timedelta(days=1),
        body_age_loader=lambda source, target: None,
    )

    assert builder.build_daily_summary_message() == "base"
    assert targets == [None]


def test_factory_builder_resolves_and_forwards_target() -> None:
    calls: list[date | None] = []
    resolved = SimpleNamespace(
        build_daily_summary_message=lambda target_date=None: calls.append(target_date)
        or "factory report"
    )
    builder = FactoryDailySummaryMessageBuilder(lambda: resolved)

    assert builder.build_daily_summary_message(TARGET) == "factory report"
    assert calls == [TARGET]
