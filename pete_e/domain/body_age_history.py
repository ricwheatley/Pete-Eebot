"""Typed body-age history port and legacy DAL compatibility adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from typing import Protocol, TypedDict, cast


class BodyAgeHistoryRow(TypedDict, total=False):
    """Persistence-neutral fields accepted from body-age history rows."""

    date: object
    body_age_years: object
    body: object


class BodyAgeHistoryReader(Protocol):
    """Read body-age rows for an inclusive calendar window."""

    def read_body_age_history(
        self,
        start_date: date,
        end_date: date,
    ) -> Iterable[BodyAgeHistoryRow]: ...


def _materialize_history_rows(fetched: object) -> list[object]:
    if fetched is None:
        return []
    if isinstance(fetched, list):
        return cast(list[object], fetched)
    return list(cast(Iterable[object], fetched))


def _call_history_loader(
    loader: Callable[..., object],
    *args: object,
) -> list[object]:
    try:
        fetched = loader(*args)
    except Exception:
        return []
    return _materialize_history_rows(fetched)


def _load_legacy_history_rows(
    source: object,
    start_date: date,
    target_date: date,
) -> list[object]:
    get_range: object = getattr(source, "get_historical_data", None)
    if callable(get_range):
        return _call_history_loader(get_range, start_date, target_date)

    get_metrics: object = getattr(source, "get_historical_metrics", None)
    if callable(get_metrics):
        return _call_history_loader(get_metrics, 8)
    return []


class LegacyBodyAgeHistoryReader:
    """Adapt the two historical DAL capabilities to the owned history port."""

    def __init__(self, source: object) -> None:
        self._source = source

    def read_body_age_history(
        self,
        start_date: date,
        end_date: date,
    ) -> list[BodyAgeHistoryRow]:
        raw_rows = _load_legacy_history_rows(self._source, start_date, end_date)
        return [
            cast(BodyAgeHistoryRow, row) for row in raw_rows if isinstance(row, dict)
        ]


__all__ = [
    "BodyAgeHistoryReader",
    "BodyAgeHistoryRow",
    "LegacyBodyAgeHistoryReader",
]
