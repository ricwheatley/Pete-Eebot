"""Safety checks shared by the disposable PostgreSQL test lane."""

from __future__ import annotations

from psycopg.conninfo import conninfo_to_dict


SAFE_DATABASE_PREFIX = "pete_e_test"
SAFE_DATABASE_HOSTS = {"127.0.0.1", "::1", "localhost"}


def validate_test_database_url(dsn: str | None) -> str:
    """Return a validated DSN or reject anything resembling an ambient DB."""

    if not dsn:
        raise ValueError("PETEEEBOT_TEST_DATABASE_URL must be set explicitly")

    parsed = conninfo_to_dict(dsn)
    database = str(parsed.get("dbname") or "")
    user = str(parsed.get("user") or "")
    host = str(parsed.get("host") or "")
    if not database.startswith(SAFE_DATABASE_PREFIX):
        raise ValueError(
            f"test database name must start with {SAFE_DATABASE_PREFIX!r}; got {database!r}"
        )
    if "test" not in user.lower():
        raise ValueError(f"test database user must contain 'test'; got {user!r}")
    if host not in SAFE_DATABASE_HOSTS:
        raise ValueError(f"test database host must be loopback-only; got {host!r}")
    return dsn
