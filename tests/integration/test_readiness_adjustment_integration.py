from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import threading
from pathlib import Path
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool
import pytest

from pete_e.infrastructure.postgres_dal import PostgresDal


pytestmark = pytest.mark.integration


def _seed_plan(dsn: str) -> tuple[int, int, int]:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DELETE FROM training_plans")
        plan_id = connection.execute(
            """
            INSERT INTO training_plans (start_date, weeks, is_active)
            VALUES (%s, 1, true)
            RETURNING id;
            """,
            (date(2026, 8, 17),),
        ).fetchone()[0]
        week_id = connection.execute(
            """
            INSERT INTO training_plan_weeks (plan_id, week_number)
            VALUES (%s, 1)
            RETURNING id;
            """,
            (plan_id,),
        ).fetchone()[0]
        workout_id = connection.execute(
            """
            INSERT INTO training_plan_workouts (
                week_id,
                day_of_week,
                sets,
                baseline_sets,
                reps,
                rir,
                baseline_rir,
                is_cardio
            )
            VALUES (%s, 1, 5, 5, 5, 2, 2, false)
            RETURNING id;
            """,
            (week_id,),
        ).fetchone()[0]
    return int(plan_id), int(week_id), int(workout_id)


def _apply_args(
    plan_id: int,
    *,
    source: str = "a",
    policy_version: str = "policy-v1",
    set_multiplier: float = 0.8,
    rir_increment: int = 1,
) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "week_number": 1,
        "week_start_date": date(2026, 8, 17),
        "policy_version": policy_version,
        "source_data_hash": source * 64,
        "baseline_prescription_hash": "b" * 64,
        "set_multiplier": set_multiplier,
        "rir_increment": rir_increment,
        "source_summary": {"source": source},
        "decision_payload": {"policy_version": policy_version, "source": source},
    }


def _read_state(dsn: str, workout_id: int) -> tuple[int, float | None, int, float | None]:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            """
            SELECT sets, rir, baseline_sets, baseline_rir
            FROM training_plan_workouts
            WHERE id = %s;
            """,
            (workout_id,),
        ).fetchone()
    return int(row[0]), None if row[1] is None else float(row[1]), int(row[2]), (
        None if row[3] is None else float(row[3])
    )


def test_repeated_and_changed_decisions_converge_from_baseline(postgres_test_dsn: str) -> None:
    plan_id, week_id, workout_id = _seed_plan(postgres_test_dsn)
    pool = ConnectionPool(conninfo=postgres_test_dsn, min_size=1, max_size=3)
    dal = PostgresDal(pool=pool)
    try:
        first = dal.apply_plan_adjustment(**_apply_args(plan_id))
        after_one = _read_state(postgres_test_dsn, workout_id)
        second = dal.apply_plan_adjustment(**_apply_args(plan_id))
        after_two = _read_state(postgres_test_dsn, workout_id)

        changed = dal.apply_plan_adjustment(
            **_apply_args(
                plan_id,
                source="c",
                set_multiplier=0.6,
                rir_increment=2,
            )
        )
        changed_duplicate = dal.apply_plan_adjustment(
            **_apply_args(
                plan_id,
                source="c",
                set_multiplier=0.6,
                rir_increment=2,
            )
        )
        after_changed = _read_state(postgres_test_dsn, workout_id)

        neutral = dal.apply_plan_adjustment(
            **_apply_args(
                plan_id,
                source="d",
                set_multiplier=1.0,
                rir_increment=0,
            )
        )
        after_neutral = _read_state(postgres_test_dsn, workout_id)

        with psycopg.connect(postgres_test_dsn) as connection:
            ledger_count = connection.execute(
                "SELECT count(*) FROM plan_readiness_adjustments WHERE plan_id = %s",
                (plan_id,),
            ).fetchone()[0]
            effective_id = connection.execute(
                "SELECT effective_readiness_adjustment_id FROM training_plan_weeks WHERE id = %s",
                (week_id,),
            ).fetchone()[0]
            audit = connection.execute(
                """
                SELECT policy_version, source_summary, decision_json, result_snapshot
                FROM plan_readiness_adjustments
                WHERE id = %s;
                """,
                (neutral["adjustment_id"],),
            ).fetchone()

        assert first["created"] is True
        assert second == {"adjustment_id": first["adjustment_id"], "created": False}
        assert after_one == after_two == (4, 3.0, 5, 2.0)
        assert changed["adjustment_id"] == changed_duplicate["adjustment_id"]
        assert changed_duplicate["created"] is False
        assert after_changed == (3, 4.0, 5, 2.0)
        assert after_neutral == (5, 2.0, 5, 2.0)
        assert ledger_count == 3
        assert effective_id == neutral["adjustment_id"]
        assert audit[0] == "policy-v1"
        assert audit[1] == {"source": "d"}
        assert audit[2] == {"policy_version": "policy-v1", "source": "d"}
        assert audit[3] == [
            {
                "workout_id": workout_id,
                "baseline_sets": 5,
                "effective_sets": 5,
                "baseline_rir": 2.0,
                "effective_rir": 2.0,
            }
        ]
    finally:
        pool.close()


def test_zero_set_placeholder_is_not_promoted_by_readiness_adjustment(
    postgres_test_dsn: str,
) -> None:
    plan_id, week_id, workout_id = _seed_plan(postgres_test_dsn)
    with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
        placeholder_id = connection.execute(
            """
            INSERT INTO training_plan_workouts (
                week_id,
                day_of_week,
                sets,
                baseline_sets,
                reps,
                rir,
                baseline_rir,
                is_cardio,
                comment
            )
            VALUES (%s, 2, 0, 0, 0, NULL, NULL, false, 'Rest day')
            RETURNING id;
            """,
            (week_id,),
        ).fetchone()[0]

    pool = ConnectionPool(conninfo=postgres_test_dsn, min_size=1, max_size=2)
    dal = PostgresDal(pool=pool)
    try:
        result = dal.apply_plan_adjustment(**_apply_args(plan_id))
    finally:
        pool.close()

    with psycopg.connect(postgres_test_dsn) as connection:
        placeholder = connection.execute(
            """
            SELECT sets, baseline_sets, rir, baseline_rir
            FROM training_plan_workouts
            WHERE id = %s;
            """,
            (placeholder_id,),
        ).fetchone()
        snapshot = connection.execute(
            """
            SELECT result_snapshot
            FROM plan_readiness_adjustments
            WHERE id = %s;
            """,
            (result["adjustment_id"],),
        ).fetchone()[0]

    assert placeholder == (0, 0, None, None)
    assert [row["workout_id"] for row in snapshot] == [workout_id]


def test_concurrent_duplicate_adjustments_share_one_ledger_row(postgres_test_dsn: str) -> None:
    plan_id, _, workout_id = _seed_plan(postgres_test_dsn)
    pool = ConnectionPool(conninfo=postgres_test_dsn, min_size=2, max_size=4)
    dal = PostgresDal(pool=pool)
    barrier = threading.Barrier(2)

    def apply_once() -> dict[str, Any]:
        barrier.wait(timeout=10)
        return dal.apply_plan_adjustment(**_apply_args(plan_id))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: apply_once(), range(2)))

        with psycopg.connect(postgres_test_dsn) as connection:
            ledger_count = connection.execute(
                "SELECT count(*) FROM plan_readiness_adjustments WHERE plan_id = %s",
                (plan_id,),
            ).fetchone()[0]

        assert {result["adjustment_id"] for result in results} == {results[0]["adjustment_id"]}
        assert sorted(result["created"] for result in results) == [False, True]
        assert ledger_count == 1
        assert _read_state(postgres_test_dsn, workout_id) == (4, 3.0, 5, 2.0)
    finally:
        pool.close()


def test_failed_effective_update_rolls_back_ledger_marker(postgres_test_dsn: str) -> None:
    plan_id, week_id, workout_id = _seed_plan(postgres_test_dsn)
    with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE OR REPLACE FUNCTION fail_readiness_effective_update()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.sets <> OLD.sets THEN
                    RAISE EXCEPTION 'injected readiness update failure';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
        connection.execute(
            """
            CREATE TRIGGER test_fail_readiness_effective_update
            BEFORE UPDATE ON training_plan_workouts
            FOR EACH ROW EXECUTE FUNCTION fail_readiness_effective_update();
            """
        )

    pool = ConnectionPool(conninfo=postgres_test_dsn, min_size=1, max_size=2)
    dal = PostgresDal(pool=pool)
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="injected readiness update failure"):
            dal.apply_plan_adjustment(**_apply_args(plan_id))
    finally:
        pool.close()
        with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
            connection.execute(
                "DROP TRIGGER IF EXISTS test_fail_readiness_effective_update ON training_plan_workouts"
            )
            connection.execute("DROP FUNCTION IF EXISTS fail_readiness_effective_update()")

    with psycopg.connect(postgres_test_dsn) as connection:
        ledger_count = connection.execute(
            "SELECT count(*) FROM plan_readiness_adjustments WHERE plan_id = %s",
            (plan_id,),
        ).fetchone()[0]
        effective_id = connection.execute(
            "SELECT effective_readiness_adjustment_id FROM training_plan_weeks WHERE id = %s",
            (week_id,),
        ).fetchone()[0]

    assert ledger_count == 0
    assert effective_id is None
    assert _read_state(postgres_test_dsn, workout_id) == (5, 2.0, 5, 2.0)


def test_migration_backfills_existing_effective_values_as_initial_baseline(
    postgres_test_dsn: str,
) -> None:
    migration = Path(
        "pete_e/migrations/20260820_add_readiness_adjustment_idempotency.sql"
    ).read_text(encoding="utf-8")
    with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
        connection.execute("DELETE FROM training_plans")
        connection.execute("DROP TABLE plan_readiness_adjustments CASCADE")
        connection.execute(
            "ALTER TABLE training_plan_weeks DROP COLUMN IF EXISTS effective_readiness_adjustment_id"
        )
        connection.execute(
            """
            ALTER TABLE training_plan_workouts
                DROP COLUMN baseline_sets,
                DROP COLUMN baseline_rir;
            """
        )
        plan_id = connection.execute(
            """
            INSERT INTO training_plans (start_date, weeks, is_active)
            VALUES (%s, 1, true)
            RETURNING id;
            """,
            (date(2026, 8, 17),),
        ).fetchone()[0]
        week_id = connection.execute(
            """
            INSERT INTO training_plan_weeks (plan_id, week_number)
            VALUES (%s, 1)
            RETURNING id;
            """,
            (plan_id,),
        ).fetchone()[0]
        workout_id = connection.execute(
            """
            INSERT INTO training_plan_workouts (
                week_id, day_of_week, sets, reps, rir, is_cardio
            )
            VALUES (%s, 1, 3, 5, 4, false)
            RETURNING id;
            """,
            (week_id,),
        ).fetchone()[0]
        placeholder_id = connection.execute(
            """
            INSERT INTO training_plan_workouts (
                week_id, day_of_week, sets, reps, rir, is_cardio, comment
            )
            VALUES (%s, 2, 0, 0, NULL, false, 'Rest day')
            RETURNING id;
            """,
            (week_id,),
        ).fetchone()[0]

        connection.execute(migration)
        row = connection.execute(
            """
            SELECT sets, baseline_sets, rir, baseline_rir
            FROM training_plan_workouts
            WHERE id = %s;
            """,
            (workout_id,),
        ).fetchone()
        placeholder = connection.execute(
            """
            SELECT sets, baseline_sets, rir, baseline_rir
            FROM training_plan_workouts
            WHERE id = %s;
            """,
            (placeholder_id,),
        ).fetchone()

    assert row == (3, 3, 4.0, 4.0)
    assert placeholder == (0, 0, None, None)
