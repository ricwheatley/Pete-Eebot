"""PostgreSQL persistence for coached-person profiles."""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pete_e.domain.profile import UserProfile
from pete_e.infrastructure.postgres_dal import get_pool


class PostgresProfileRepository:
    def __init__(self, pool: ConnectionPool | None = None) -> None:
        self.pool = pool or get_pool()

    @staticmethod
    def _profile_from_row(row: dict[str, Any]) -> UserProfile:
        return UserProfile(
            id=int(row["id"]),
            slug=str(row["slug"]),
            display_name=str(row["display_name"]),
            date_of_birth=row.get("date_of_birth"),
            height_cm=int(row["height_cm"]) if row.get("height_cm") is not None else None,
            goal_weight_kg=float(row["goal_weight_kg"]) if row.get("goal_weight_kg") is not None else None,
            timezone=str(row.get("timezone") or "Europe/London"),
            is_default=bool(row["is_default"]),
            is_active=bool(row["is_active"]),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def create_profile(
        self,
        *,
        slug: str,
        display_name: str,
        date_of_birth: date | None,
        height_cm: int | None,
        goal_weight_kg: float | None,
        timezone: str,
        is_default: bool,
        owner_user_id: int | None = None,
    ) -> UserProfile:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    conn.autocommit = False
                    if is_default:
                        cur.execute("UPDATE user_profiles SET is_default = false WHERE is_default = true")
                    cur.execute(
                        """
                        INSERT INTO user_profiles (
                            slug,
                            display_name,
                            date_of_birth,
                            height_cm,
                            goal_weight_kg,
                            timezone,
                            is_default
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING
                            id,
                            slug,
                            display_name,
                            date_of_birth,
                            height_cm,
                            goal_weight_kg,
                            timezone,
                            is_default,
                            is_active,
                            created_at,
                            updated_at
                        """,
                        (
                            slug,
                            display_name,
                            date_of_birth,
                            height_cm,
                            goal_weight_kg,
                            timezone,
                            is_default,
                        ),
                    )
                    row = cur.fetchone()
                    if owner_user_id is not None:
                        cur.execute(
                            """
                            INSERT INTO auth_user_profiles (user_id, profile_id)
                            VALUES (%s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (owner_user_id, int(row["id"])),
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        return self._profile_from_row(row)

    def get_default_profile(self) -> UserProfile | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        slug,
                        display_name,
                        date_of_birth,
                        height_cm,
                        goal_weight_kg,
                        timezone,
                        is_default,
                        is_active,
                        created_at,
                        updated_at
                    FROM user_profiles
                    WHERE is_default = true
                      AND is_active = true
                    ORDER BY id
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
        return self._profile_from_row(row) if row else None

    def get_profile_by_slug(self, slug: str) -> UserProfile | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        slug,
                        display_name,
                        date_of_birth,
                        height_cm,
                        goal_weight_kg,
                        timezone,
                        is_default,
                        is_active,
                        created_at,
                        updated_at
                    FROM user_profiles
                    WHERE slug = %s
                      AND is_active = true
                    LIMIT 1
                    """,
                    (slug,),
                )
                row = cur.fetchone()
        return self._profile_from_row(row) if row else None

    def list_profiles_for_user(self, user_id: int) -> list[UserProfile]:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        p.id,
                        p.slug,
                        p.display_name,
                        p.date_of_birth,
                        p.height_cm,
                        p.goal_weight_kg,
                        p.timezone,
                        p.is_default,
                        p.is_active,
                        p.created_at,
                        p.updated_at
                    FROM auth_user_profiles aup
                    JOIN user_profiles p ON p.id = aup.profile_id
                    WHERE aup.user_id = %s
                      AND p.is_active = true
                    ORDER BY p.is_default DESC, p.slug
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
        return [self._profile_from_row(row) for row in rows]

    def list_profiles(self) -> list[UserProfile]:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        slug,
                        display_name,
                        date_of_birth,
                        height_cm,
                        goal_weight_kg,
                        timezone,
                        is_default,
                        is_active,
                        created_at,
                        updated_at
                    FROM user_profiles
                    WHERE is_active = true
                    ORDER BY is_default DESC, slug
                    """
                )
                rows = cur.fetchall()
        return [self._profile_from_row(row) for row in rows]
