from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest

from pete_e.infrastructure.postgres_dal import PostgresDal


pytestmark = pytest.mark.integration


class _SingleConnectionPoolPort:
    """Expose one real psycopg connection through the DAL's pool port."""

    def __init__(self, connection) -> None:
        self._connection = connection
        self.closed = False

    @contextmanager
    def connection(self):
        yield self._connection


def test_nutrition_insert_uses_real_psycopg_and_rolls_back(postgres_connection) -> None:
    dal = PostgresDal(pool=_SingleConnectionPoolPort(postgres_connection))
    record = {
        "client_event_id": "integration-event-1",
        "dedupe_fingerprint": "integration-fingerprint-1",
        "eaten_at": "2026-08-20T12:30:00+00:00",
        "local_date": date(2026, 8, 20),
        "protein_g": 40,
        "carbs_g": 65,
        "fat_g": 18,
        "alcohol_g": 0,
        "fiber_g": 7,
        "estimated_total_calories": 582,
        "calories_est": 582,
        "source": "integration_test",
        "context": "post_run",
        "confidence": "high",
        "meal_label": "test meal",
        "notes": None,
        "raw_payload_json": {"lane": "postgres-integration"},
    }

    with postgres_connection.transaction(force_rollback=True):
        inserted, duplicate = dal.insert_nutrition_log(record)
        repeated, repeated_duplicate = dal.insert_nutrition_log(record)

        assert duplicate is False
        assert repeated_duplicate is True
        assert repeated["id"] == inserted["id"]
        with postgres_connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM nutrition_log WHERE client_event_id = %s",
                (record["client_event_id"],),
            )
            assert cursor.fetchone() == (1,)

    with postgres_connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM nutrition_log WHERE client_event_id = %s",
            (record["client_event_id"],),
        )
        assert cursor.fetchone() == (0,)
