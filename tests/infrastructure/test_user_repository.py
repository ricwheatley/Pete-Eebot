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


def test_has_user_with_role_checks_active_users() -> None:
    cur = MagicMock()
    cur.fetchone.return_value = (1,)
    pool = _pool_with_cursor(cur)
    repo = PostgresUserRepository(pool=pool)

    assert repo.has_user_with_role(ROLE_OWNER) is True

    sql, params = cur.execute.call_args.args
    assert "FROM auth_user_roles ur" in sql
    assert "JOIN auth_users u" in sql
    assert "u.is_active = true" in sql
    assert params == (ROLE_OWNER,)


def test_update_user_password_updates_hash_and_timestamp() -> None:
    cur = MagicMock()
    now = datetime.now(timezone.utc)
    pool = _pool_with_cursor(cur)
    repo = PostgresUserRepository(pool=pool)

    repo.update_user_password(7, "new-hash", now)

    sql, params = cur.execute.call_args.args
    assert "UPDATE auth_users" in sql
    assert "password_changed_at = %s" in sql
    assert params == ("new-hash", now, 7)


def test_revoke_user_sessions_revokes_active_sessions_only() -> None:
    cur = MagicMock()
    now = datetime.now(timezone.utc)
    pool = _pool_with_cursor(cur)
    repo = PostgresUserRepository(pool=pool)

    repo.revoke_user_sessions(7, now)

    sql, params = cur.execute.call_args.args
    assert "UPDATE auth_sessions" in sql
    assert "revoked_at IS NULL" in sql
    assert params == (now, 7)
