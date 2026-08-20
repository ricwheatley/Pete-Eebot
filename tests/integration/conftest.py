from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from psycopg import ClientCursor

from tests.postgres_safety import validate_test_database_url


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def postgres_test_dsn(request: pytest.FixtureRequest) -> str:
    """Initialize only an explicitly opted-in, unmistakably test-only DB."""

    if not request.config.getoption("--run-postgres"):
        pytest.skip("PostgreSQL lane requires --run-postgres")

    try:
        dsn = validate_test_database_url(os.getenv("PETEEEBOT_TEST_DATABASE_URL"))
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc

    schema_files = [ROOT / "init-db" / "schema.sql", *sorted((ROOT / "migrations").glob("*.sql"))]
    with psycopg.connect(dsn, autocommit=True, cursor_factory=ClientCursor) as connection:
        # The guard above makes this an explicitly disposable database. Reset the
        # schema so a prior failed bootstrap cannot leave relation-type conflicts.
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
        for sql_file in schema_files:
            connection.execute(sql_file.read_text(encoding="utf-8"))
    return dsn


@pytest.fixture()
def postgres_connection(postgres_test_dsn: str):
    """Yield a real psycopg connection; callers own a force-rollback transaction."""

    with psycopg.connect(postgres_test_dsn) as connection:
        yield connection
