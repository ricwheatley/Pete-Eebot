from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from pete_e.domain.auth import ROLE_OWNER
from pete_e.infrastructure.user_repository import PostgresUserRepository


def _pool_with_cursor(cur: MagicMock) -> MagicMock:
    pool = MagicMock()
    conn = MagicMock()
    pool.connection.return_value.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    return pool


def test_create_user_persists_user_and_roles() -> None:
    cur = MagicMock()
    now = datetime.now(timezone.utc)
    cur.fetchone.return_value = {
        "id": 7,
        "username": "Pete",
        "email": "pete@example.com",
        "display_name": "Pete",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
    }
    pool = _pool_with_cursor(cur)
    repo = PostgresUserRepository(pool=pool)

    user = repo.create_user(
        username="Pete",
        username_normalized="pete",
        email="pete@example.com",
        email_normalized="pete@example.com",
        display_name="Pete",
        password_hash="pbkdf2_sha256$1$salt$hash",
        roles=(ROLE_OWNER,),
    )

    assert user.id == 7
    assert user.roles == (ROLE_OWNER,)
    insert_sql = cur.execute.call_args.args[0]
    assert "INSERT INTO auth_users" in insert_sql
    cur.executemany.assert_called_once()
    role_sql, role_values = cur.executemany.call_args.args
    assert "INSERT INTO auth_user_roles" in role_sql
    assert role_values == [(7, ROLE_OWNER)]


def test_get_user_for_active_session_filters_revoked_and_expired_sessions() -> None:
    cur = MagicMock()
    now = datetime.now(timezone.utc)
    cur.fetchone.return_value = {
        "id": 7,
        "username": "Pete",
        "email": None,
        "display_name": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
    }
    cur.fetchall.return_value = [{"role_name": ROLE_OWNER}]
    pool = _pool_with_cursor(cur)
    repo = PostgresUserRepository(pool=pool)

    user = repo.get_user_for_active_session("a" * 64, now + timedelta(seconds=1))

    assert user is not None
    assert user.roles == (ROLE_OWNER,)
    session_sql = cur.execute.call_args_list[0].args[0]
    assert "FROM auth_sessions s" in session_sql
    assert "s.revoked_at IS NULL" in session_sql
    assert "s.expires_at > %s" in session_sql
    assert "u.is_active = true" in session_sql
