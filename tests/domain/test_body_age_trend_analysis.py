"""Pure tests for the typed body-age history and analysis boundary."""

from __future__ import annotations

import ast
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from pete_e.domain.body_age_history import BodyAgeHistoryReader, BodyAgeHistoryRow
from pete_e.domain.body_age_trend import (
    BodyAgeTrend,
    analyze_body_age_trend,
    extract_body_age_value,
)


TARGET = date(2026, 8, 23)


class _Floatable:
    def __float__(self) -> float:
        return 37.75


class _InvalidFloatable:
    def __float__(self) -> float:
        raise ValueError("not numeric")


class _Reader:
    def __init__(self, rows: list[BodyAgeHistoryRow]) -> None:
        self.rows = rows
        self.requests: list[tuple[date, date]] = []

    def read_body_age_history(
        self,
        start_date: date,
        end_date: date,
    ) -> list[BodyAgeHistoryRow]:
        self.requests.append((start_date, end_date))
        return self.rows


def test_owned_reader_port_supplies_explicit_rows_to_pure_analysis() -> None:
    rows: list[BodyAgeHistoryRow] = [
        {"date": TARGET - timedelta(days=7), "body_age_years": Decimal("39.25")},
        {"date": TARGET, "body_age_years": _Floatable()},
    ]
    reader: BodyAgeHistoryReader = _Reader(rows)

    trend = analyze_body_age_trend(
        reader.read_body_age_history(TARGET - timedelta(days=7), TARGET),
        TARGET,
    )

    assert trend == BodyAgeTrend(sample_date=TARGET, value=37.8, delta=-1.5)
    assert reader.requests == [(TARGET - timedelta(days=7), TARGET)]


def test_pure_analysis_ignores_every_invalid_row_branch() -> None:
    invalid_rows: list[object] = [
        None,
        "not a row",
        {"date": "", "body_age_years": 30.0},
        {"date": "invalid", "body_age_years": 31.0},
        {"date": object(), "body_age_years": 32.0},
        {"date": TARGET, "body_age_years": ""},
        {"date": TARGET, "body_age_years": "invalid"},
        {"date": TARGET, "body_age_years": _InvalidFloatable()},
        {"date": TARGET, "body": []},
        {"date": TARGET - timedelta(days=8), "body_age_years": 33.0},
        {"date": TARGET + timedelta(days=1), "body_age_years": 34.0},
    ]

    assert analyze_body_age_trend(invalid_rows, TARGET) == BodyAgeTrend(
        None, None, None
    )


def test_value_extraction_preserves_flat_precedence_and_nested_fallback() -> None:
    assert extract_body_age_value({"body_age_years": 0}) == 0.0
    assert extract_body_age_value({"body_age_years": False}) == 0.0
    assert extract_body_age_value({"body": {"body_age_years": "38.4"}}) == 38.4
    assert (
        extract_body_age_value(
            {
                "body_age_years": "invalid",
                "body": {"body_age_years": 38.4},
            }
        )
        is None
    )


def test_analysis_keeps_stable_duplicate_and_exact_date_semantics() -> None:
    rows: list[object] = [
        {"date": TARGET, "body_age_years": 39.0},
        {"date": TARGET - timedelta(days=7), "body_age_years": 41.0},
        {"date": TARGET, "body_age_years": 38.0},
        {"date": TARGET - timedelta(days=7), "body_age_years": 40.0},
    ]

    assert analyze_body_age_trend(rows, TARGET) == BodyAgeTrend(TARGET, 38.0, -3.0)


def test_analysis_does_not_use_a_nearby_date_for_delta() -> None:
    rows: list[object] = [
        {"date": TARGET - timedelta(days=6), "body_age_years": 40.0},
        {"date": TARGET - timedelta(days=1), "body_age_years": 38.0},
    ]

    assert analyze_body_age_trend(rows, TARGET) == BodyAgeTrend(
        TARGET - timedelta(days=1),
        38.0,
        None,
    )


def test_pure_boundary_has_no_framework_or_infrastructure_imports() -> None:
    module_path = Path("pete_e/domain/body_age_trend.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )

    forbidden_prefixes = (
        "fastapi",
        "starlette",
        "psycopg",
        "pete_e.api",
        "pete_e.api_routes",
        "pete_e.application",
        "pete_e.cli",
        "pete_e.infrastructure",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imports)
