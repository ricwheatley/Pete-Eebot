"""Real PostgreSQL characterization for atomic full-plan persistence."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool
from psycopg.types.json import Json
import pytest

from pete_e.infrastructure.postgres_dal import PostgresDal


pytestmark = pytest.mark.integration

EXERCISE_ID = 990_073


def _pool(dsn: str) -> ConnectionPool:
    return ConnectionPool(conninfo=dsn, min_size=1, max_size=2, open=True)


def _clear_plans(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DELETE FROM training_plans")


def _seed_exercise(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO wger_exercise (id, uuid, name, is_main_lift)
            VALUES (%s, %s, %s, false)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
            """,
            (EXERCISE_ID, uuid4(), "Plan persistence integration lift"),
        )


def _seed_active_plan(dsn: str) -> int:
    _clear_plans(dsn)
    with psycopg.connect(dsn, autocommit=True) as connection:
        row = connection.execute(
            """
            INSERT INTO training_plans (start_date, weeks, is_active, metadata)
            VALUES (%s, 1, true, %s)
            RETURNING id
            """,
            (date(2026, 8, 24), Json({"marker": "previous-active"})),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _minimal_plan(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "start_date": date(2026, 8, 31),
        "weeks": 1,
        "plan_weeks": [{"week_number": 1, "workouts": []}],
    }
    payload.update(overrides)
    return payload


def _assert_only_previous_plan_remains(dsn: str, previous_plan_id: int) -> None:
    with psycopg.connect(dsn) as connection:
        plans = connection.execute(
            "SELECT id, is_active FROM training_plans ORDER BY id"
        ).fetchall()
        week_count = connection.execute(
            "SELECT count(*) FROM training_plan_weeks"
        ).fetchone()
        workout_count = connection.execute(
            "SELECT count(*) FROM training_plan_workouts"
        ).fetchone()

    assert plans == [(previous_plan_id, True)]
    assert week_count == (0,)
    assert workout_count == (0,)


def test_full_plan_rows_order_json_baselines_and_sequential_activation(
    postgres_test_dsn: str,
) -> None:
    _clear_plans(postgres_test_dsn)
    _seed_exercise(postgres_test_dsn)
    pool = _pool(postgres_test_dsn)
    dal = PostgresDal(pool=pool)
    metadata = {
        "source": "real-postgres-characterization",
        "trace": {"stages": ["mapped", "persisted"]},
    }
    strength_details = {
        "display_name": "Tempo squat",
        "prescription": {"tempo": "3-1-1"},
    }
    cardio_details = {
        "display_name": "Easy run",
        "distance_km": 8.5,
    }
    comment_details = {
        "display_name": "Recovery review",
        "notes": ["sleep", "mobility"],
    }
    first_payload = {
        "start_date": date(2026, 8, 31),
        "weeks": "fallback-to-list-length",
        "metadata": metadata,
        "plan_weeks": [
            {"week_number": "2", "is_test": True, "workouts": []},
            {
                "week_number": "10",
                "workouts": [
                    {
                        "day_of_week": "2",
                        "exercise_id": str(EXERCISE_ID),
                        "sets": "5",
                        "reps": "3",
                        "rir": 2.5,
                        "rir_cue": 1.5,
                        "percent_1rm": Decimal("80.25"),
                        "target_weight_kg": Decimal("92.50"),
                        "scheduled_time": "07:05:06",
                        "slot": "22:00:00",
                        "is_cardio": False,
                        "comment": "strength",
                        "optional": "false",
                        "recovery_focused": 0,
                        "details": strength_details,
                        "programmed_difficulty": "4",
                    },
                    {
                        "day_of_week": True,
                        "exercise_id": None,
                        "sets": 1,
                        "reps": 1,
                        "scheduled_time": "invalid",
                        "slot": "18:30",
                        "is_cardio": True,
                        "comment": "cardio",
                        "optional": False,
                        "recovery_focused": True,
                        "details": cardio_details,
                    },
                    {
                        "day_of_week": 7,
                        "exercise_id": None,
                        "sets": 0,
                        "reps": 0,
                        "rir": None,
                        "rir_cue": 3,
                        "is_cardio": False,
                        "comment": "comment only",
                        "details": comment_details,
                    },
                ],
            },
        ],
    }

    try:
        first_plan_id = dal.save_full_plan(first_payload)

        with psycopg.connect(postgres_test_dsn) as connection:
            plan_row = connection.execute(
                """
                SELECT start_date, weeks, is_active, metadata
                FROM training_plans
                WHERE id = %s
                """,
                (first_plan_id,),
            ).fetchone()
            week_rows = connection.execute(
                """
                SELECT id, week_number, is_test
                FROM training_plan_weeks
                WHERE plan_id = %s
                ORDER BY id
                """,
                (first_plan_id,),
            ).fetchall()
            workout_rows = connection.execute(
                """
                SELECT
                    week_id,
                    day_of_week,
                    exercise_id,
                    sets,
                    baseline_sets,
                    reps,
                    rir,
                    baseline_rir,
                    percent_1rm,
                    target_weight_kg,
                    rir_cue,
                    scheduled_time,
                    is_cardio,
                    comment,
                    optional,
                    recovery_focused,
                    details,
                    programmed_difficulty
                FROM training_plan_workouts
                ORDER BY id
                """
            ).fetchall()

        assert isinstance(first_plan_id, int)
        assert plan_row == (date(2026, 8, 31), 2, True, metadata)
        assert [(row[1], row[2]) for row in week_rows] == [(10, False), (2, True)]
        week_ten_id = week_rows[0][0]
        assert workout_rows == [
            (
                week_ten_id,
                2,
                EXERCISE_ID,
                5,
                5,
                3,
                2.5,
                2.5,
                Decimal("80.25"),
                Decimal("92.50"),
                Decimal("1.5"),
                time(7, 5, 6),
                False,
                "strength",
                True,
                False,
                strength_details,
                4,
            ),
            (
                week_ten_id,
                1,
                None,
                1,
                1,
                1,
                None,
                None,
                None,
                None,
                None,
                time(18, 30),
                True,
                "cardio",
                False,
                True,
                cardio_details,
                None,
            ),
            (
                week_ten_id,
                7,
                None,
                0,
                0,
                0,
                None,
                None,
                None,
                None,
                Decimal("3.0"),
                None,
                False,
                "comment only",
                False,
                False,
                comment_details,
                None,
            ),
        ]

        second_plan_id = dal.save_full_plan(_minimal_plan(start_date=date(2026, 9, 7)))
        with psycopg.connect(postgres_test_dsn) as connection:
            activation_rows = connection.execute(
                "SELECT id, is_active FROM training_plans ORDER BY id"
            ).fetchall()
            active_count = connection.execute(
                "SELECT count(*) FROM training_plans WHERE is_active"
            ).fetchone()

        assert activation_rows == [
            (first_plan_id, False),
            (second_plan_id, True),
        ]
        assert active_count == (1,)
    finally:
        pool.close()
        _clear_plans(postgres_test_dsn)


def test_plan_insert_failure_restores_the_previous_active_plan(
    postgres_test_dsn: str,
) -> None:
    previous_plan_id = _seed_active_plan(postgres_test_dsn)
    pool = _pool(postgres_test_dsn)
    dal = PostgresDal(pool=pool)
    try:
        with pytest.raises(psycopg.errors.InvalidDatetimeFormat):
            dal.save_full_plan(_minimal_plan(start_date="not-a-date"))
    finally:
        pool.close()

    _assert_only_previous_plan_remains(postgres_test_dsn, previous_plan_id)
    _clear_plans(postgres_test_dsn)


def test_week_insert_failure_restores_the_previous_active_plan(
    postgres_test_dsn: str,
) -> None:
    previous_plan_id = _seed_active_plan(postgres_test_dsn)
    with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE FUNCTION fail_plan_week_insert()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'injected plan week failure';
            END
            $$
            """
        )
        connection.execute(
            """
            CREATE TRIGGER test_fail_plan_week_insert
            BEFORE INSERT ON training_plan_weeks
            FOR EACH ROW EXECUTE FUNCTION fail_plan_week_insert()
            """
        )

    pool = _pool(postgres_test_dsn)
    dal = PostgresDal(pool=pool)
    try:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="injected plan week failure",
        ):
            dal.save_full_plan(_minimal_plan())
    finally:
        pool.close()
        with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
            connection.execute(
                "DROP TRIGGER test_fail_plan_week_insert ON training_plan_weeks"
            )
            connection.execute("DROP FUNCTION fail_plan_week_insert()")

    _assert_only_previous_plan_remains(postgres_test_dsn, previous_plan_id)
    _clear_plans(postgres_test_dsn)


@pytest.mark.parametrize(
    ("workout", "error_type"),
    [
        (
            {
                "day_of_week": 1,
                "exercise_id": 2_147_000_000,
                "sets": 1,
                "reps": 1,
            },
            psycopg.errors.ForeignKeyViolation,
        ),
        (
            {
                "day_of_week": 1,
                "exercise_id": None,
                "sets": 1,
                "reps": 1,
                "programmed_difficulty": 11,
            },
            psycopg.errors.CheckViolation,
        ),
        (
            {
                "day_of_week": 1,
                "exercise_id": None,
                "sets": 1,
                "reps": 1,
                "details": object(),
            },
            TypeError,
        ),
    ],
)
def test_workout_fk_constraint_and_json_failures_leave_no_partial_rows(
    postgres_test_dsn: str,
    workout: dict[str, object],
    error_type: type[Exception],
) -> None:
    previous_plan_id = _seed_active_plan(postgres_test_dsn)
    pool = _pool(postgres_test_dsn)
    dal = PostgresDal(pool=pool)
    try:
        with pytest.raises(error_type):
            dal.save_full_plan(
                _minimal_plan(plan_weeks=[{"week_number": 1, "workouts": [workout]}])
            )
    finally:
        pool.close()

    _assert_only_previous_plan_remains(postgres_test_dsn, previous_plan_id)
    _clear_plans(postgres_test_dsn)


def test_deferred_commit_failure_rolls_back_the_active_plan_transition(
    postgres_test_dsn: str,
) -> None:
    previous_plan_id = _seed_active_plan(postgres_test_dsn)
    with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE FUNCTION fail_marked_plan_at_commit()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.metadata ->> 'fail_commit' = 'true' THEN
                    RAISE EXCEPTION 'injected plan commit failure';
                END IF;
                RETURN NEW;
            END
            $$
            """
        )
        connection.execute(
            """
            CREATE CONSTRAINT TRIGGER test_fail_marked_plan_at_commit
            AFTER INSERT ON training_plans
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION fail_marked_plan_at_commit()
            """
        )

    pool = _pool(postgres_test_dsn)
    dal = PostgresDal(pool=pool)
    try:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="injected plan commit failure",
        ):
            dal.save_full_plan(_minimal_plan(metadata={"fail_commit": True}))
    finally:
        pool.close()
        with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
            connection.execute(
                "DROP TRIGGER test_fail_marked_plan_at_commit ON training_plans"
            )
            connection.execute("DROP FUNCTION fail_marked_plan_at_commit()")

    _assert_only_previous_plan_remains(postgres_test_dsn, previous_plan_id)
    _clear_plans(postgres_test_dsn)


def test_migrated_schema_supports_plan_save_through_a_dml_only_role(
    postgres_test_dsn: str,
) -> None:
    _clear_plans(postgres_test_dsn)
    role_name = f"pete_plan_dml_{uuid4().hex[:12]}"
    password = f"test-{uuid4().hex}"
    database_name = str(
        psycopg.conninfo.conninfo_to_dict(postgres_test_dsn).get("dbname") or ""
    )
    role_dsn = psycopg.conninfo.make_conninfo(
        postgres_test_dsn,
        user=role_name,
        password=password,
    )

    with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role_name),
                sql.Literal(password),
            )
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database_name),
                sql.Identifier(role_name),
            )
        )
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                sql.Identifier(role_name)
            )
        )
        connection.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE ON "
                "training_plans, training_plan_weeks, training_plan_workouts TO {}"
            ).format(sql.Identifier(role_name))
        )
        connection.execute(
            sql.SQL(
                "GRANT USAGE, SELECT ON SEQUENCE "
                "training_plans_id_seq, training_plan_weeks_id_seq, "
                "training_plan_workouts_id_seq TO {}"
            ).format(sql.Identifier(role_name))
        )
        assert connection.execute(
            "SELECT has_schema_privilege(%s, 'public', 'CREATE')",
            (role_name,),
        ).fetchone() == (False,)

    pool = _pool(role_dsn)
    dal = PostgresDal(pool=pool)
    try:
        plan_id = dal.save_full_plan(_minimal_plan())
        with psycopg.connect(role_dsn) as connection:
            persisted = connection.execute(
                "SELECT start_date, weeks, is_active FROM training_plans WHERE id = %s",
                (plan_id,),
            ).fetchone()
        assert persisted == (date(2026, 8, 31), 1, True)
    finally:
        pool.close()
        with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name))
            )
            connection.execute(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name))
            )
        _clear_plans(postgres_test_dsn)
