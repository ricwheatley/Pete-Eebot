"""Tests for the Postgres DAL implementation.

These tests require a running PostgreSQL instance. If the environment variable
`TEST_DATABASE_URL` is not set, the tests will be skipped. The tests mirror the
JSON DAL round-trip to ensure functional parity.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

TEST_DB_URL = os.getenv("TEST_DATABASE_URL")

if TEST_DB_URL:
    # Make the Postgres DAL use the test database URL
    os.environ["DATABASE_URL"] = TEST_DB_URL
    from pete_e.config import settings
    from pete_e.data_access.postgres_dal import PostgresDal
    import psycopg
else:  # pragma: no cover - environment without postgres
    PostgresDal = None


@pytest.mark.skipif(PostgresDal is None, reason="TEST_DATABASE_URL not configured")
def test_postgres_dal_roundtrip(tmp_path, monkeypatch):
    """Basic round-trip test for PostgresDal."""
    # Redirect file-based settings to temp path (for completeness)
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)

    # Initialise schema
    schema = Path("init-db/schema.sql").read_text()
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(schema)

    dal = PostgresDal()

    # Daily summary roundtrip
    summary = {"withings": {"weight": 80}, "apple": {"steps": 1000}}
    day = date(2024, 1, 1)
    dal.save_daily_summary(summary, day)
    assert dal.get_daily_summary(day)["withings"]["weight"] == 80

    history = dal.load_history()
    assert history[day.isoformat()]["withings"]["weight"] == 80

    metrics = dal.get_historical_metrics(1)
    assert metrics[0]["apple"]["steps"] == 1000

    data = dal.get_historical_data(day, day)
    assert data[0]["withings"]["weight"] == 80

    # Training plan persistence
    plan = {"start": day.isoformat(), "weeks": []}
    dal.save_training_plan(plan, day)
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT plan FROM training_plans WHERE start_date = %s;", (day,)
            )
            row = cur.fetchone()
            assert row and row[0]["start"] == day.isoformat()

