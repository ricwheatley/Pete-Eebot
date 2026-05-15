from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from pete_e.infrastructure.profile_repository import PostgresProfileRepository


def _pool_with_cursor(cur: MagicMock) -> MagicMock:
    pool = MagicMock()
    conn = MagicMock()
    pool.connection.return_value.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    return pool


def _profile_row(**overrides):
    now = datetime.now(timezone.utc)
    row = {
        "id": 3,
        "slug": "default",
        "display_name": "Default profile",
        "date_of_birth": date(1990, 1, 1),
        "height_cm": 175,
        "goal_weight_kg": 75,
        "timezone": "Europe/London",
        "is_default": True,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def test_create_profile_persists_profile_and_optional_assignment() -> None:
    cur = MagicMock()
    cur.fetchone.return_value = _profile_row(slug="athlete")
    repo = PostgresProfileRepository(pool=_pool_with_cursor(cur))

    profile = repo.create_profile(
        slug="athlete",
        display_name="Athlete",
        date_of_birth=date(1990, 1, 1),
        height_cm=180,
        goal_weight_kg=82,
        timezone="Europe/London",
        is_default=False,
        owner_user_id=7,
    )

    assert profile.slug == "athlete"
    insert_sql = cur.execute.call_args_list[0].args[0]
    assert "INSERT INTO user_profiles" in insert_sql
    assignment_sql = cur.execute.call_args_list[1].args[0]
    assert "INSERT INTO auth_user_profiles" in assignment_sql


def test_get_default_profile_filters_active_default() -> None:
    cur = MagicMock()
    cur.fetchone.return_value = _profile_row()
    repo = PostgresProfileRepository(pool=_pool_with_cursor(cur))

    profile = repo.get_default_profile()

    assert profile is not None
    assert profile.is_default is True
    sql = cur.execute.call_args.args[0]
    assert "WHERE is_default = true" in sql
    assert "AND is_active = true" in sql


def test_list_profiles_for_user_uses_assignment_table() -> None:
    cur = MagicMock()
    cur.fetchall.return_value = [_profile_row(slug="default"), _profile_row(id=4, slug="family")]
    repo = PostgresProfileRepository(pool=_pool_with_cursor(cur))

    profiles = repo.list_profiles_for_user(7)

    assert [profile.slug for profile in profiles] == ["default", "family"]
    sql = cur.execute.call_args.args[0]
    assert "FROM auth_user_profiles aup" in sql
    assert "JOIN user_profiles p" in sql


def test_list_profiles_returns_active_profiles() -> None:
    cur = MagicMock()
    cur.fetchall.return_value = [_profile_row(slug="default")]
    repo = PostgresProfileRepository(pool=_pool_with_cursor(cur))

    profiles = repo.list_profiles()

    assert [profile.slug for profile in profiles] == ["default"]
    sql = cur.execute.call_args.args[0]
    assert "FROM user_profiles" in sql
    assert "WHERE is_active = true" in sql
