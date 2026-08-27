"""Characterization of the legacy body-age trend compatibility facade."""

from __future__ import annotations

from collections import UserDict
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from pete_e.domain import body_age


TARGET = date(2026, 8, 23)
EMPTY_TREND = body_age.BodyAgeTrend(sample_date=None, value=None, delta=None)


def _row(day: object, value: object, *, nested: bool = False) -> dict[str, object]:
    if nested:
        return {"date": day, "body": {"body_age_years": value}}
    return {"date": day, "body_age_years": value}


@pytest.mark.parametrize(
    "dal",
    [
        None,
        object(),
        SimpleNamespace(get_historical_data=None, get_historical_metrics=None),
    ],
)
def test_missing_reader_capability_returns_exact_empty_trend(dal: object) -> None:
    assert body_age.get_body_age_trend(dal, target_date=TARGET) == EMPTY_TREND


def test_preferred_range_reader_receives_exact_window_and_blocks_fallback() -> None:
    calls: list[tuple[object, ...]] = []

    def get_range(start_date: date, end_date: date) -> list[dict[str, object]]:
        calls.append(("range", start_date, end_date))
        return [_row(TARGET, 38.4)]

    def get_metrics(days: int) -> list[dict[str, object]]:
        calls.append(("metrics", days))
        return [_row(TARGET, 99.0)]

    dal = SimpleNamespace(
        get_historical_data=get_range,
        get_historical_metrics=get_metrics,
    )

    assert body_age.get_body_age_trend(
        dal, target_date=TARGET
    ) == body_age.BodyAgeTrend(
        sample_date=TARGET,
        value=38.4,
        delta=None,
    )
    assert calls == [("range", TARGET - timedelta(days=7), TARGET)]


@pytest.mark.parametrize("preferred", [None, 0, "not callable"])
def test_noncallable_preferred_reader_uses_eight_row_fallback(
    preferred: object,
) -> None:
    calls: list[int] = []

    def get_metrics(days: int) -> tuple[dict[str, object]]:
        calls.append(days)
        return (_row(TARGET, 37.2),)

    dal = SimpleNamespace(
        get_historical_data=preferred,
        get_historical_metrics=get_metrics,
    )

    assert body_age.get_body_age_trend(dal, target_date=TARGET).value == 37.2
    assert calls == [8]


@pytest.mark.parametrize("reader_name", ["range", "fallback"])
def test_synchronous_reader_exceptions_are_suppressed(reader_name: str) -> None:
    calls: list[str] = []

    def fail(*_args: object) -> object:
        calls.append(reader_name)
        raise RuntimeError("loader failed")

    fallback_calls: list[int] = []
    if reader_name == "range":
        dal = SimpleNamespace(
            get_historical_data=fail,
            get_historical_metrics=lambda days: fallback_calls.append(days),
        )
    else:
        dal = SimpleNamespace(get_historical_metrics=fail)

    assert body_age.get_body_age_trend(dal, target_date=TARGET) == EMPTY_TREND
    assert calls == [reader_name]
    assert fallback_calls == []


@pytest.mark.parametrize("preferred_result", [None, []])
def test_empty_preferred_result_does_not_fall_back(preferred_result: object) -> None:
    fallback_calls: list[int] = []
    dal = SimpleNamespace(
        get_historical_data=lambda *_: preferred_result,
        get_historical_metrics=lambda days: fallback_calls.append(days),
    )

    assert body_age.get_body_age_trend(dal, target_date=TARGET) == EMPTY_TREND
    assert fallback_calls == []


def _as_none(_rows: list[dict[str, object]]) -> None:
    return None


def _as_list(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return rows


def _as_tuple(rows: list[dict[str, object]]) -> tuple[dict[str, object], ...]:
    return tuple(rows)


def _as_generator(rows: list[dict[str, object]]) -> Iterator[dict[str, object]]:
    yield from rows


@pytest.mark.parametrize("reader_name", ["range", "fallback"])
@pytest.mark.parametrize(
    ("container", "expected"),
    [
        (_as_none, EMPTY_TREND),
        (_as_list, body_age.BodyAgeTrend(TARGET, 38.4, -0.6)),
        (_as_tuple, body_age.BodyAgeTrend(TARGET, 38.4, -0.6)),
        (_as_generator, body_age.BodyAgeTrend(TARGET, 38.4, -0.6)),
    ],
    ids=["none", "list", "tuple", "generator"],
)
def test_reader_result_materialization_is_preserved(
    reader_name: str,
    container: Callable[[list[dict[str, object]]], object],
    expected: body_age.BodyAgeTrend,
) -> None:
    rows = [_row(TARGET - timedelta(days=7), 39.0), _row(TARGET, 38.4)]

    def loader(*_args: object) -> object:
        return container(rows)

    if reader_name == "range":
        dal = SimpleNamespace(get_historical_data=loader)
    else:
        dal = SimpleNamespace(get_historical_metrics=loader)

    assert body_age.get_body_age_trend(dal, target_date=TARGET) == expected


@pytest.mark.parametrize("reader_name", ["range", "fallback"])
def test_iterator_failures_propagate_after_loader_returns(reader_name: str) -> None:
    def broken_rows() -> Iterator[dict[str, object]]:
        yield _row(TARGET, 38.4)
        raise RuntimeError("iteration failed")

    def loader(*_args: object) -> Iterator[dict[str, object]]:
        return broken_rows()

    if reader_name == "range":
        dal = SimpleNamespace(get_historical_data=loader)
    else:
        dal = SimpleNamespace(get_historical_metrics=loader)

    with pytest.raises(RuntimeError, match="iteration failed"):
        body_age.get_body_age_trend(dal, target_date=TARGET)


@pytest.mark.parametrize("result", [42, 3.5, object()])
def test_noniterable_reader_results_propagate_type_error(result: object) -> None:
    dal = SimpleNamespace(get_historical_data=lambda *_: result)

    with pytest.raises(TypeError):
        body_age.get_body_age_trend(dal, target_date=TARGET)


@pytest.mark.parametrize("result", ["body age", {"date": TARGET}])
def test_iterable_malformed_reader_results_are_ignored(result: object) -> None:
    dal = SimpleNamespace(get_historical_data=lambda *_: result)

    assert body_age.get_body_age_trend(dal, target_date=TARGET) == EMPTY_TREND


def test_default_target_is_local_yesterday_and_explicit_target_bypasses_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[date, date]] = []

    class FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return date(2026, 8, 24)

    dal = SimpleNamespace(
        get_historical_data=lambda start, end: requests.append((start, end)) or [],
    )
    monkeypatch.setattr(body_age, "date", FixedDate)

    assert body_age.get_body_age_trend(dal) == EMPTY_TREND
    assert (
        body_age.get_body_age_trend(dal, target_date=date(2025, 1, 10)) == EMPTY_TREND
    )
    assert requests == [
        (date(2026, 8, 16), date(2026, 8, 23)),
        (date(2025, 1, 3), date(2025, 1, 10)),
    ]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (_row(TARGET, 38), 38.0),
        (_row(TARGET, " 38.25 "), 38.2),
        (_row(TARGET, "38.25", nested=True), 38.2),
        (_row(TARGET, 0), 0.0),
        (_row(TARGET, False), 0.0),
        (_row(TARGET, True), 1.0),
    ],
    ids=["integer", "numeric-string", "nested", "zero", "false", "true"],
)
def test_flat_nested_numeric_and_falsey_values_follow_converter_semantics(
    row: dict[str, object],
    expected: float,
) -> None:
    dal = SimpleNamespace(get_historical_data=lambda *_: [row])

    assert body_age.get_body_age_trend(
        dal, target_date=TARGET
    ) == body_age.BodyAgeTrend(
        TARGET,
        expected,
        None,
    )


@pytest.mark.parametrize(
    "row",
    [
        {"date": TARGET, "body": []},
        {"date": TARGET, "body": UserDict({"body_age_years": 38.0})},
        {"date": TARGET, "body": {"body_age_years": "invalid"}},
        {"date": TARGET, "body_age_years": "invalid", "body": {"body_age_years": 38.0}},
        {"date": TARGET, "body_age_years": ""},
        {"date": TARGET, "body_age_years": object()},
    ],
)
def test_malformed_nested_and_invalid_values_are_ignored(
    row: dict[str, object],
) -> None:
    dal = SimpleNamespace(get_historical_data=lambda *_: [row])

    assert body_age.get_body_age_trend(dal, target_date=TARGET) == EMPTY_TREND


@pytest.mark.parametrize(
    "raw_date",
    [
        TARGET,
        datetime(2026, 8, 23, 21, 15),
        "2026-08-23",
        "2026-08-23T21:15:00+01:00",
    ],
)
def test_supported_date_forms_normalize_to_a_date(raw_date: object) -> None:
    dal = SimpleNamespace(get_historical_data=lambda *_: [_row(raw_date, 38.4)])

    assert body_age.get_body_age_trend(dal, target_date=TARGET).sample_date == TARGET


def test_invalid_rows_and_rows_outside_the_inclusive_window_are_ignored() -> None:
    rows: list[object] = [
        None,
        "row",
        UserDict({"date": TARGET, "body_age_years": 90.0}),
        {"date": None, "body_age_years": 91.0},
        {"date": "not-a-date", "body_age_years": 92.0},
        {"date": object(), "body_age_years": 93.0},
        _row(TARGET - timedelta(days=8), 94.0),
        _row(TARGET + timedelta(days=1), 95.0),
        _row(TARGET - timedelta(days=7), 40.0),
        _row(TARGET - timedelta(days=1), 39.0),
    ]
    dal = SimpleNamespace(get_historical_data=lambda *_: rows)

    assert body_age.get_body_age_trend(
        dal, target_date=TARGET
    ) == body_age.BodyAgeTrend(
        TARGET - timedelta(days=1),
        39.0,
        -1.0,
    )


def test_unordered_points_select_latest_sample_before_target() -> None:
    rows = [
        _row(TARGET - timedelta(days=3), 38.2),
        _row(TARGET - timedelta(days=7), 39.1),
        _row(TARGET - timedelta(days=1), 38.7),
        _row(TARGET - timedelta(days=5), 38.9),
    ]
    dal = SimpleNamespace(get_historical_data=lambda *_: rows)

    assert body_age.get_body_age_trend(
        dal, target_date=TARGET
    ) == body_age.BodyAgeTrend(
        TARGET - timedelta(days=1),
        38.7,
        -0.4,
    )


def test_same_date_duplicates_use_last_latest_and_first_exact_week_value() -> None:
    rows = [
        _row(TARGET, 39.0),
        _row(TARGET - timedelta(days=7), 41.0),
        _row(TARGET, 38.0),
        _row(TARGET - timedelta(days=7), 40.0),
    ]
    dal = SimpleNamespace(get_historical_data=lambda *_: rows)

    assert body_age.get_body_age_trend(
        dal, target_date=TARGET
    ) == body_age.BodyAgeTrend(
        TARGET,
        38.0,
        -3.0,
    )


def test_nearby_comparison_dates_do_not_supply_a_delta() -> None:
    rows = [
        _row(TARGET - timedelta(days=6), 40.0),
        _row(TARGET - timedelta(days=1), 38.0),
    ]
    dal = SimpleNamespace(get_historical_data=lambda *_: rows)

    assert body_age.get_body_age_trend(
        dal, target_date=TARGET
    ) == body_age.BodyAgeTrend(
        TARGET - timedelta(days=1),
        38.0,
        None,
    )


def test_value_and_negative_delta_use_python_one_decimal_rounding() -> None:
    rows = [
        _row(TARGET - timedelta(days=7), 39.9),
        _row(TARGET, 38.65),
    ]
    dal = SimpleNamespace(get_historical_data=lambda *_: rows)

    assert body_age.get_body_age_trend(
        dal, target_date=TARGET
    ) == body_age.BodyAgeTrend(
        TARGET,
        round(38.65, 1),
        round(38.65 - 39.9, 1),
    )
