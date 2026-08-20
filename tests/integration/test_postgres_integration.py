from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from datetime import datetime, timezone

import pytest

from pete_e.infrastructure.apple_parser import AppleHealthParser
from pete_e.infrastructure.apple_writer import AppleHealthWriter
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


def _parsed_apple_checkpoint_fixture() -> dict:
    return AppleHealthParser().parse(
        {
            "data": {
                "metrics": [
                    {
                        "name": "checkpoint_integration_metric",
                        "units": "count",
                        "data": [
                            {
                                "date": "2026-08-20 08:00:00 +0000",
                                "source": "Checkpoint Integration Watch",
                                "qty": 7,
                            }
                        ],
                    }
                ],
                "workouts": [],
            }
        }
    )


def test_apple_checkpoint_persistence_and_replay_use_real_postgres(
    postgres_connection,
) -> None:
    checkpoint = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    writer = AppleHealthWriter(postgres_connection)
    parsed = _parsed_apple_checkpoint_fixture()

    with postgres_connection.transaction(force_rollback=True):
        writer.upsert_all(parsed)
        writer.upsert_all(parsed)
        writer.save_last_import_timestamp(checkpoint)

        assert writer.get_last_import_timestamp() == checkpoint
        with postgres_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM "DailyMetric" AS daily_metric
                JOIN "MetricType" AS metric_type
                  ON metric_type.metric_id = daily_metric.metric_id
                JOIN "Device" AS device
                  ON device.device_id = daily_metric.device_id
                WHERE metric_type.name = %s AND device.name = %s
                """,
                ("checkpoint_integration_metric", "Checkpoint Integration Watch"),
            )
            assert cursor.fetchone() == (1,)


def test_apple_checkpoint_failure_rolls_back_health_write_in_real_postgres(
    postgres_connection,
) -> None:
    writer = AppleHealthWriter(postgres_connection)
    parsed = _parsed_apple_checkpoint_fixture()

    with postgres_connection.transaction(force_rollback=True):
        with pytest.raises(Exception):
            with postgres_connection.transaction():
                writer.upsert_all(parsed)
                writer.save_last_import_timestamp(None)  # type: ignore[arg-type]

        with postgres_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM "DailyMetric" AS daily_metric
                JOIN "MetricType" AS metric_type
                  ON metric_type.metric_id = daily_metric.metric_id
                JOIN "Device" AS device
                  ON device.device_id = daily_metric.device_id
                WHERE metric_type.name = %s AND device.name = %s
                """,
                ("checkpoint_integration_metric", "Checkpoint Integration Watch"),
            )
            assert cursor.fetchone() == (0,)
