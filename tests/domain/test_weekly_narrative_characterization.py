from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from pete_e.domain import narrative_builder


_TODAY = date(2025, 9, 22)


class _FixedDateTime:
    @classmethod
    def utcnow(cls) -> datetime:
        return datetime.combine(_TODAY, datetime.min.time())


@pytest.fixture
def deterministic_weekly_narrative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(narrative_builder, "datetime", _FixedDateTime)
    monkeypatch.setattr(narrative_builder.random, "choice", lambda values: values[0])
    monkeypatch.setattr(narrative_builder.random, "randint", lambda start, end: start)
    monkeypatch.setattr(
        narrative_builder, "phrase_for", lambda *args, **kwargs: "Keep going!"
    )
    monkeypatch.setattr(
        narrative_builder.narrative_utils.random, "random", lambda: 0.99
    )


def _two_week_body_days(
    *,
    current_body_age: Any,
    previous_body_age: Any,
    current_muscle: Any = None,
    previous_muscle: Any = None,
) -> dict[str, dict[str, object]]:
    days: dict[str, dict[str, object]] = {}
    for offset in range(1, 15):
        is_current_week = offset < 8
        body: dict[str, object] = {
            "body_age_years": current_body_age
            if is_current_week
            else previous_body_age,
            "muscle_pct": current_muscle if is_current_week else previous_muscle,
        }
        days[(_TODAY - timedelta(days=offset)).isoformat()] = {"body": body}
    return days


def test_weekly_narrative_empty_days_response_is_stable() -> None:
    expected = "Howdy Ric 🤠\n\nNo logs found for last week. Rest week?"

    assert narrative_builder.build_weekly_narrative({}) == expected
    assert narrative_builder.build_weekly_narrative({"days": {}}) == expected


def test_weekly_narrative_quiet_response_for_unusable_dates_is_stable(
    deterministic_weekly_narrative: None,
) -> None:
    narrative = narrative_builder.build_weekly_narrative({"days": {"not-a-date": {}}})

    assert narrative == "Howdy Ric 🤠\n\nQuiet week logged — recovery matters too."


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        (40.0, 39.0, "Body Age averaged 40.0y this week, up 1.0y from last week."),
        (39.0, 39.0, "Body Age averaged 39.0y this week, matching last week."),
    ],
)
def test_weekly_narrative_preserves_body_age_comparison_branches(
    deterministic_weekly_narrative: None,
    monkeypatch: pytest.MonkeyPatch,
    current: float,
    previous: float,
    expected: str,
) -> None:
    monkeypatch.setattr(
        narrative_builder, "compute_trend_lines", lambda *args, **kwargs: []
    )
    days = _two_week_body_days(current_body_age=current, previous_body_age=previous)

    narrative = narrative_builder.build_weekly_narrative({"days": days})

    assert expected in narrative


def test_weekly_narrative_preserves_muscle_threshold_and_invalid_metric_handling(
    deterministic_weekly_narrative: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        narrative_builder, "compute_trend_lines", lambda *args, **kwargs: []
    )
    days = _two_week_body_days(
        current_body_age="not-a-number",
        previous_body_age=None,
        current_muscle=40.4,
        previous_muscle=40.0,
    )

    narrative = narrative_builder.build_weekly_narrative({"days": days})

    assert "Average sleep was 0h per night." in narrative
    assert "Muscle composition" not in narrative
    assert "Body Age" not in narrative


def test_weekly_narrative_filters_trend_samples_and_preserves_line_order(
    deterministic_weekly_narrative: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_trends(
        samples: list[tuple[date, dict[str, Any]]],
        *,
        as_of: date,
        limit: int,
    ) -> list[str]:
        captured["dates"] = [sample_date for sample_date, _ in samples]
        captured["as_of"] = as_of
        captured["limit"] = limit
        return ["First trend.", "Second trend."]

    monkeypatch.setattr(narrative_builder, "compute_trend_lines", fake_trends)
    days: dict[str, object] = {
        (_TODAY - timedelta(days=1)).isoformat(): {},
        (_TODAY + timedelta(days=2)).isoformat(): {},
        (_TODAY - timedelta(days=30)).isoformat(): [],
        "not-a-date": {},
    }

    narrative = narrative_builder.build_weekly_narrative({"days": days})

    assert captured == {
        "dates": [_TODAY - timedelta(days=1), _TODAY + timedelta(days=2)],
        "as_of": _TODAY - timedelta(days=1),
        "limit": 2,
    }
    assert narrative.index("Momentum backdrop - First trend.") < narrative.index(
        "Second trend."
    )
