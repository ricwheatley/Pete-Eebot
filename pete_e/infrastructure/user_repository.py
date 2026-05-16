"""PostgreSQL persistence for browser users, roles, and sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from pete_e.domain.auth import AuthUser, RoleName, StoredUser, UserSession, normalize_roles
from pete_e.infrastructure.postgres_dal import get_pool


class PostgresUserRepository:
    def __init__(self, pool: ConnectionPool | None = None) -> None:
        self.pool = pool or get_pool()

    @staticmethod
    def _roles_from_rows(rows: list[dict[str, Any]]) -> tuple[RoleName, ...]:
        return normalize_roles(row["role_name"] for row in rows)

    @staticmethod
    def _user_from_row(row: dict[str, Any], roles: tuple[RoleName, ...]) -> AuthUser:
        return AuthUser(
            id=int(row["id"]),
            username=str(row["username"]),
            email=row.get("email"),
            display_name=row.get("display_name"),
            roles=roles,
            is_active=bool(row["is_active"]),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            last_login_at=row.get("last_login_at"),
            mfa_enabled=bool(row.get("mfa_enabled", False)),
        )

    @staticmethod
    def _session_from_row(row: dict[str, Any]) -> UserSession:
        return UserSession(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            last_seen_at=row.get("last_seen_at"),
            revoked_at=row.get("revoked_at"),
            ip_address=str(row["ip_address"]) if row.get("ip_address") is not None else None,
            user_agent=row.get("user_agent"),
        )

    def _fetch_roles(self, cur, user_id: int) -> tuple[RoleName, ...]:
        cur.execute(
            """
            SELECT role_name
            FROM auth_user_roles
            WHERE user_id = %s
            ORDER BY role_name
            """,
            (user_id,),
        )
        return self._roles_from_rows(cur.fetchall())

    def create_user(
        self,
        *,
        username: str,
        username_normalized: str,
        email: str | None,
        email_normalized: str | None,
        display_name: str | None,
        password_hash: str,
        roles: tuple[RoleName, ...],
    ) -> AuthUser:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    conn.autocommit = False
                    cur.execute(
                        """
                        INSERT INTO auth_users (
                            username,
                            username_normalized,
                            email,
                            email_normalized,
                            display_name,
                            password_hash
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING
                            id,
                            username,
                            email,
                            display_name,
                            is_active,
                            created_at,
                            updated_at,
                            last_login_at
                        """,
                        (
                            username,
                            username_normalized,
                            email,
                            email_normalized,
                            display_name,
                            password_hash,
                        ),
                    )
                    row = cur.fetchone()
                    user_id = int(row["id"])
                    cur.executemany(
                        """
                        INSERT INTO auth_user_roles (user_id, role_name)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        [(user_id, role) for role in roles],
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

        return self._user_from_row(row, roles)

    def get_user_by_login(self, login_normalized: str) -> StoredUser | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        username,
                        email,
                        display_name,
                        password_hash,
                        is_active,
                        created_at,
                        updated_at,
                        last_login_at
                        , COALESCE(mfa_enabled, false) AS mfa_enabled
                    FROM auth_users
                    WHERE username_normalized = %s OR email_normalized = %s
                    LIMIT 1
                    """,
                    (login_normalized, login_normalized),
                )
                row = cur.fetchone()
                if not row:
                    return None
                roles = self._fetch_roles(cur, int(row["id"]))

        user = self._user_from_row(row, roles)
        return StoredUser(user=user, password_hash=str(row["password_hash"]))

    def get_user_by_id(self, user_id: int) -> AuthUser | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        username,
                        email,
                        display_name,
                        is_active,
                        created_at,
                        updated_at,
                        last_login_at
                        , COALESCE(mfa_enabled, false) AS mfa_enabled
                    FROM auth_users
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                roles = self._fetch_roles(cur, user_id)

        return self._user_from_row(row, roles)

    def list_users(self) -> list[AuthUser]:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        username,
                        email,
                        display_name,
                        is_active,
                        created_at,
                        updated_at,
                        last_login_at,
                        COALESCE(mfa_enabled, false) AS mfa_enabled
                    FROM auth_users
                    ORDER BY username_normalized ASC
                    """
                )
                rows = cur.fetchall()
                users: list[AuthUser] = []
                for row in rows:
                    roles = self._fetch_roles(cur, int(row["id"]))
                    users.append(self._user_from_row(row, roles))
                return users

    def has_user_with_role(self, role: RoleName) -> bool:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM auth_user_roles ur
                    JOIN auth_users u ON u.id = ur.user_id
                    WHERE ur.role_name = %s
                      AND u.is_active = true
                    LIMIT 1
                    """,
                    (role,),
                )
                return cur.fetchone() is not None

    def active_owner_count_excluding(self, user_id: int | None = None) -> int:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)::int
                    FROM auth_user_roles ur
                    JOIN auth_users u ON u.id = ur.user_id
                    WHERE ur.role_name = 'owner'
                      AND u.is_active = true
                      AND (%s IS NULL OR u.id <> %s)
                    """,
                    (user_id, user_id),
                )
                row = cur.fetchone()
                return int(row[0] if row else 0)

    def set_user_roles(self, user_id: int, roles: tuple[RoleName, ...]) -> AuthUser:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    conn.autocommit = False
                    cur.execute("SELECT id FROM auth_users WHERE id = %s FOR UPDATE", (user_id,))
                    if cur.fetchone() is None:
                        raise KeyError(user_id)
                    cur.execute("DELETE FROM auth_user_roles WHERE user_id = %s", (user_id,))
                    cur.executemany(
                        """
                        INSERT INTO auth_user_roles (user_id, role_name)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        [(user_id, role) for role in roles],
                    )
                    cur.execute(
                        """
                        UPDATE auth_users
                        SET updated_at = now()
                        WHERE id = %s
                        RETURNING
                            id,
                            username,
                            email,
                            display_name,
                            is_active,
                            created_at,
                            updated_at,
                            last_login_at,
                            COALESCE(mfa_enabled, false) AS mfa_enabled
                        """,
                        (user_id,),
                    )
                    row = cur.fetchone()
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        return self._user_from_row(row, roles)

    def deactivate_user(self, user_id: int, when: datetime) -> AuthUser:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE auth_users
                    SET is_active = false,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING
                        id,
                        username,
                        email,
                        display_name,
                        is_active,
                        created_at,
                        updated_at,
                        last_login_at,
                        COALESCE(mfa_enabled, false) AS mfa_enabled
                    """,
                    (when, user_id),
                )
                row = cur.fetchone()
                if not row:
                    raise KeyError(user_id)
                roles = self._fetch_roles(cur, user_id)
        return self._user_from_row(row, roles)

    def update_user_password(self, user_id: int, password_hash: str, when: datetime) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth_users
                    SET password_hash = %s,
                        password_changed_at = %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (password_hash, when, user_id),
                )

    def revoke_user_sessions(self, user_id: int, when: datetime) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = COALESCE(revoked_at, %s)
                    WHERE user_id = %s
                      AND revoked_at IS NULL
                    """,
                    (when, user_id),
                )

    def record_successful_login(self, user_id: int, when: datetime) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE auth_users SET last_login_at = %s, updated_at = now() WHERE id = %s",
                    (when, user_id),
                )

    def create_session(
        self,
        *,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> UserSession:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO auth_sessions (
                        user_id,
                        token_hash,
                        expires_at,
                        ip_address,
                        user_agent
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING
                        id,
                        user_id,
                        created_at,
                        expires_at,
                        last_seen_at,
                        revoked_at,
                        ip_address,
                        user_agent
                    """,
                    (user_id, token_hash, expires_at, ip_address, user_agent),
                )
                row = cur.fetchone()
        return self._session_from_row(row)

    def get_user_for_active_session(self, token_hash: str, now: datetime) -> AuthUser | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        u.id,
                        u.username,
                        u.email,
                        u.display_name,
                        u.is_active,
                        u.created_at,
                        u.updated_at,
                        u.last_login_at
                        , COALESCE(u.mfa_enabled, false) AS mfa_enabled
                    FROM auth_sessions s
                    JOIN auth_users u ON u.id = s.user_id
                    WHERE s.token_hash = %s
                      AND s.revoked_at IS NULL
                      AND s.expires_at > %s
                      AND u.is_active = true
                    LIMIT 1
                    """,
                    (token_hash, now),
                )
                row = cur.fetchone()
                if not row:
                    return None
                roles = self._fetch_roles(cur, int(row["id"]))
        return self._user_from_row(row, roles)

    def set_user_mfa_state(
        self,
        user_id: int,
        *,
        secret: str | None,
        enabled: bool,
        recovery_code_hashes: list[str],
        when: datetime,
    ) -> AuthUser:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE auth_users
                    SET mfa_secret = %s,
                        mfa_enabled = %s,
                        mfa_recovery_code_hashes = %s::jsonb,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING
                        id,
                        username,
                        email,
                        display_name,
                        is_active,
                        created_at,
                        updated_at,
                        last_login_at,
                        COALESCE(mfa_enabled, false) AS mfa_enabled
                    """,
                    (secret, enabled, Json(list(recovery_code_hashes)), when, user_id),
                )
                row = cur.fetchone()
                if not row:
                    raise KeyError(user_id)
                roles = self._fetch_roles(cur, user_id)
        return self._user_from_row(row, roles)

    def get_user_mfa(self, user_id: int) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        mfa_secret,
                        COALESCE(mfa_enabled, false) AS mfa_enabled,
                        COALESCE(mfa_recovery_code_hashes, '[]'::jsonb) AS mfa_recovery_code_hashes
                    FROM auth_users
                    WHERE id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "secret": row.get("mfa_secret"),
            "enabled": bool(row.get("mfa_enabled")),
            "recovery_code_hashes": list(row.get("mfa_recovery_code_hashes") or []),
        }

    def replace_recovery_code_hashes(self, user_id: int, hashes: list[str], when: datetime) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth_users
                    SET mfa_recovery_code_hashes = %s::jsonb,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (Json(list(hashes)), when, user_id),
                )

    def touch_session(self, token_hash: str, when: datetime) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth_sessions
                    SET last_seen_at = %s
                    WHERE token_hash = %s
                      AND revoked_at IS NULL
                      AND expires_at > %s
                    """,
                    (when, token_hash, when),
                )

    def revoke_session(self, token_hash: str, when: datetime) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = COALESCE(revoked_at, %s)
                    WHERE token_hash = %s
                    """,
                    (when, token_hash),
                )
