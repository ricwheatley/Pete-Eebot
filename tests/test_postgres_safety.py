from __future__ import annotations

import pytest

from tests.postgres_safety import validate_test_database_url


pytestmark = pytest.mark.unit


def test_postgres_guard_accepts_explicit_local_test_database() -> None:
    dsn = "postgresql://pete_test:secret@127.0.0.1:5432/pete_e_test_ci"

    assert validate_test_database_url(dsn) == dsn


@pytest.mark.parametrize(
    "dsn, message",
    [
        (None, "must be set explicitly"),
        ("postgresql://pete_test:secret@127.0.0.1/postgres", "name must start"),
        ("postgresql://app:secret@127.0.0.1/pete_e_test_ci", "user must contain"),
        ("postgresql://pete_test:secret@db.example.com/pete_e_test_ci", "loopback-only"),
    ],
)
def test_postgres_guard_rejects_ambient_or_non_test_targets(
    dsn: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_test_database_url(dsn)
