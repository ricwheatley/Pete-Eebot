from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

import pytest

from pete_e.domain.weekly_narrative import analyze_weekly_metrics


_TODAY = date(2025, 9, 22)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _compare(
    current: int | float,
    previous: int | float | None,
    unit: str = "",
    context: str = "",
) -> str:
    return f"{current}{unit}|{previous}{unit}|{context}"


def _no_trends(
    samples: Sequence[tuple[date | datetime, Mapping[str, Any]]],
    *,
    as_of: date | None = None,
    limit: int | None = None,
) -> list[str]:
    return []


def test_analysis_orders_metric_and_trend_insights() -> None:
    captured: dict[str, object] = {}

    def trends(
        samples: Sequence[tuple[date | datetime, Mapping[str, Any]]],
        *,
        as_of: date | None = None,
        limit: int | None = None,
    ) -> list[str]:
        captured["dates"] = [sample_date for sample_date, _ in samples]
        captured["as_of"] = as_of
        captured["limit"] = limit
        return ["First trend.", "Second trend."]

    days = {
        (_TODAY - timedelta(days=1)).isoformat(): {
            "strength": [{"volume_kg": 100}],
            "activity": {"steps": 1_000},
            "sleep": {"asleep_minutes": 420},
            "body": {"muscle_pct": 41.0, "body_age_years": 38.0},
        },
        (_TODAY - timedelta(days=8)).isoformat(): {
            "strength": [{"volume_kg": 200}],
            "activity": {"steps": 2_000},
            "sleep": {"asleep_minutes": 480},
            "body": {"muscle_pct": 40.0, "body_age_years": 39.0},
        },
    }

    analysis = analyze_weekly_metrics(
        days,
        today=_TODAY,
        compare=_compare,
        trends=trends,
        parse_date=_parse_date,
    )

    assert analysis.insights == (
        "Lifting volume hit 100kg|200kg| this week.",
        "You clocked 1000steps|2000steps|this week.",
        "Average sleep was 7h|8h|per night.",
        "Muscle composition averaged 41.0% this week, up 1.0% from last week.",
        "Body Age averaged 38.0y this week, down 1.0y from last week.",
        "Momentum backdrop - First trend.",
        "Second trend.",
    )
    assert captured == {
        "dates": [_TODAY - timedelta(days=8), _TODAY - timedelta(days=1)],
        "as_of": _TODAY - timedelta(days=1),
        "limit": 2,
    }


def test_analysis_preserves_no_previous_week_baselines() -> None:
    days = {
        (_TODAY - timedelta(days=1)).isoformat(): {
            "strength": [{"volume_kg": 75}],
            "activity": {"steps": 900},
            "sleep": {"asleep_minutes": 360},
            "muscle_pct": 42,
            "body_age_years": 37,
        }
    }

    analysis = analyze_weekly_metrics(
        days,
        today=_TODAY,
        compare=_compare,
        trends=_no_trends,
        parse_date=_parse_date,
    )

    assert analysis.insights == (
        "Lifting volume hit 75kg|Nonekg| this week.",
        "You clocked 900steps|Nonesteps|this week.",
        "Average sleep was 6h|Noneh|per night.",
        "Muscle composition averaged 42.0% this week.",
        "Body Age averaged 37.0y this week.",
    )


def test_analysis_ignores_small_muscle_change_and_invalid_body_values() -> None:
    days = {
        (_TODAY - timedelta(days=1)).isoformat(): {
            "body": {"muscle_pct": 40.4, "body_age_years": "not-a-number"}
        },
        (_TODAY - timedelta(days=8)).isoformat(): {
            "body": {"muscle_pct": 40.0, "body_age_years": object()}
        },
    }

    analysis = analyze_weekly_metrics(
        days,
        today=_TODAY,
        compare=_compare,
        trends=_no_trends,
        parse_date=_parse_date,
    )

    assert analysis.insights == ("Average sleep was 0h|0h|per night.",)


def test_analysis_reports_downward_muscle_and_matching_body_age() -> None:
    days = {
        (_TODAY - timedelta(days=1)).isoformat(): {
            "body": {"muscle_pct": 39.0, "body_age_years": 38.0}
        },
        (_TODAY - timedelta(days=8)).isoformat(): {
            "body": {"muscle_pct": 40.0, "body_age_years": 38.0}
        },
    }

    analysis = analyze_weekly_metrics(
        days,
        today=_TODAY,
        compare=_compare,
        trends=_no_trends,
        parse_date=_parse_date,
    )

    assert (
        "Muscle composition averaged 39.0% this week, down 1.0% from last week."
        in analysis.insights
    )
    assert "Body Age averaged 38.0y this week, matching last week." in analysis.insights


def test_analysis_filters_unusable_samples_and_caps_future_as_of_date() -> None:
    captured: dict[str, object] = {}

    def trends(
        samples: Sequence[tuple[date | datetime, Mapping[str, Any]]],
        *,
        as_of: date | None = None,
        limit: int | None = None,
    ) -> list[str]:
        captured["dates"] = [sample_date for sample_date, _ in samples]
        captured["as_of"] = as_of
        return ["Only trend."]

    days: dict[str, object] = {
        (_TODAY - timedelta(days=30)).isoformat(): {},
        (_TODAY + timedelta(days=2)).isoformat(): {},
        (_TODAY - timedelta(days=40)).isoformat(): [],
        "invalid": {},
    }

    analysis = analyze_weekly_metrics(
        days,
        today=_TODAY,
        compare=_compare,
        trends=trends,
        parse_date=_parse_date,
    )

    assert analysis.insights == ("Momentum backdrop - Only trend.",)
    assert captured == {
        "dates": [_TODAY - timedelta(days=30), _TODAY + timedelta(days=2)],
        "as_of": _TODAY - timedelta(days=1),
    }


@pytest.mark.parametrize(
    "days",
    [
        {"invalid": {}},
        {(_TODAY - timedelta(days=30)).isoformat(): {}},
    ],
)
def test_analysis_can_return_no_insights(days: dict[str, object]) -> None:
    analysis = analyze_weekly_metrics(
        days,
        today=_TODAY,
        compare=_compare,
        trends=_no_trends,
        parse_date=_parse_date,
    )

    assert analysis.insights == ()


def test_analysis_preserves_missing_strength_volume_error() -> None:
    days = {(_TODAY - timedelta(days=1)).isoformat(): {"strength": [{}]}}

    with pytest.raises(KeyError, match="volume_kg"):
        analyze_weekly_metrics(
            days,
            today=_TODAY,
            compare=_compare,
            trends=_no_trends,
            parse_date=_parse_date,
        )
