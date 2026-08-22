from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from pete_e.infrastructure.schema_migrations import reset_development_database
from tests.postgres_safety import validate_test_database_url


@pytest.fixture(scope="session")
def postgres_test_dsn(request: pytest.FixtureRequest) -> str:
    """Initialize only an explicitly opted-in, unmistakably test-only DB."""

    if not request.config.getoption("--run-postgres"):
        pytest.skip("PostgreSQL lane requires --run-postgres")

    try:
        dsn = validate_test_database_url(os.getenv("PETEEEBOT_TEST_DATABASE_URL"))
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc

    database_name = str(psycopg.conninfo.conninfo_to_dict(dsn).get("dbname") or "")
    reset_development_database(
        dsn,
        confirm_database=database_name,
        destructive_confirmation=True,
    )
    return dsn


@pytest.fixture()
def postgres_connection(postgres_test_dsn: str):
    """Yield a real psycopg connection; callers own a force-rollback transaction."""

    with psycopg.connect(postgres_test_dsn) as connection:
        yield connection


@pytest.fixture()
def disposable_database_factory(postgres_test_dsn: str):
    """Create isolated databases inside the explicitly disposable test server."""

    admin_dsn = psycopg.conninfo.make_conninfo(postgres_test_dsn, dbname="postgres")
    created: list[str] = []

    def create(label: str) -> str:
        safe_label = "".join(character for character in label.lower() if character.isalnum())[:16]
        database_name = f"pete_e_test_{safe_label}_{uuid4().hex[:8]}"
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created.append(database_name)
        return psycopg.conninfo.make_conninfo(postgres_test_dsn, dbname=database_name)

    yield create

    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        for database_name in created:
            if not database_name.startswith("pete_e_test_"):
                raise AssertionError(f"Refusing unsafe test database cleanup: {database_name}")
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))
