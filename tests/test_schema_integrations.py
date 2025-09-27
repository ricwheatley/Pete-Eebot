from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from pete_e.cli import messenger
from pete_e.domain import narrative_builder
from pete_e.domain.narrative_builder import NarrativeBuilder


class _DeterministicRandom:
    def choice(self, seq):
        if not seq:
            raise ValueError("choice sequence was empty")
        return seq[0]

    def randint(self, a, b):
        return a

    def random(self):
        return 0.0


@pytest.fixture
def fixed_random(monkeypatch):
    deterministic = _DeterministicRandom()
    monkeypatch.setattr(narrative_builder, "random", deterministic)
    monkeypatch.setattr(narrative_builder.narrative_utils.random, "random", lambda: 0.99)
    monkeypatch.setattr(narrative_builder.narrative_utils.random, "choice", lambda seq: seq[0])
    return deterministic


@pytest.fixture(autouse=True)
def stub_phrase_picker(monkeypatch):
    monkeypatch.setattr(narrative_builder, "phrase_for", lambda *_, **__: "Keep composing!")


def _extract_table_columns(sql_text: str, table_name: str) -> list[str]:
    pattern = rf"CREATE TABLE\s+{re.escape(table_name)}\s*\((.*?)\);"
    match = re.search(pattern, sql_text, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        raise AssertionError(f"Could not find definition for table '{table_name}'.")

    block = match.group(1)
    columns: list[str] = []
    for line in block.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped or stripped.startswith("--"):
            continue
        column_name = stripped.split()[0].strip('"')
        columns.append(column_name)
    return columns


def _extract_daily_summary_select(sql_text: str) -> str:
    pattern = r"SELECT\s+(.*?)\s+FROM\s+generate_series\s*\(\s*p_start"
    match = re.search(pattern, sql_text, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        raise AssertionError("Could not locate daily_summary SELECT statement.")
    return match.group(1)


def test_withings_daily_table_includes_body_composition_columns():
    schema_sql = Path("init-db/schema.sql").read_text(encoding="utf-8")
    columns = _extract_table_columns(schema_sql, "withings_daily")

    assert "muscle_pct" in columns
    assert "water_pct" in columns


_EXPECTED_DAILY_SUMMARY_COLUMNS = {
    "muscle_pct",
    "water_pct",
    "hrv_sdnn_ms",
    "vo2_max",
}


def test_daily_summary_view_select_includes_expected_columns() -> None:
    sql_text = Path("init-db/schema.sql").read_text(encoding="utf-8")
    select_section = _extract_daily_summary_select(sql_text)

    for column in _EXPECTED_DAILY_SUMMARY_COLUMNS:
        assert re.search(rf"\b{re.escape(column)}\b", select_section), (
            f"Expected column '{column}' in daily_summary SELECT of init-db/schema.sql"
        )


def test_daily_summary_pipeline_surfaces_new_schema_fields(monkeypatch, fixed_random):
    target = date(2025, 9, 21)
    summary_row = {
        "date": target,
        "weight_kg": 82.0,
        "body_fat_pct": 18.5,
        "muscle_pct": 41.8,
        "water_pct": 55.2,
        "hr_resting": 52,
        "hrv_sdnn_ms": 75.0,
        "steps": 9800,
        "calories_active": 760,
        "sleep_asleep_minutes": 420,
    }

    history_rows: list[dict[str, Any]] = []
    for offset in range(14):
        day = target - timedelta(days=offset)
        history_rows.append(
            {
                "date": day,
                "muscle_pct": 42.0 if offset < 7 else 39.5,
                "hrv_sdnn_ms": 75.0 if offset == 0 else (70.0 if offset < 7 else 65.0),
            }
        )

    class StubDal:
        def __init__(self):
            self.summary_calls: list[date | None] = []
            self.history_requests: list[int] = []

        def get_daily_summary(self, target_date: date | None) -> dict[str, Any]:
            self.summary_calls.append(target_date)
            return dict(summary_row)

        def get_historical_metrics(self, days: int) -> list[dict[str, Any]]:
            self.history_requests.append(days)
            return list(history_rows)

        def get_historical_data(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
            return []

    class StubOrchestrator:
        def __init__(self):
            self.dal = StubDal()
            self.narrative_builder = NarrativeBuilder()
            self.summary_requests: list[date | None] = []

        def get_daily_summary(self, target_date: date | None = None) -> str:
            self.summary_requests.append(target_date)
            summary_data = self.dal.get_daily_summary(target_date)
            return self.narrative_builder.build_daily_summary(summary_data)

    monkeypatch.setattr(messenger.body_age, "get_body_age_trend", lambda *_, **__: None)

    orch = StubOrchestrator()
    summary = messenger.build_daily_summary(orchestrator=orch, target_date=target)

    assert "- Muscle: 41.8%" in summary
    assert "- Hydration: 55.2%" in summary
    assert "Muscle trend: 42.0% avg this week (up 2.5% vs prior)." in summary
    assert "HRV: 75 ms" in summary
    assert "↗" in summary
    assert orch.summary_requests == [target]
    assert orch.dal.summary_calls == [target]
    assert 14 in orch.dal.history_requests
