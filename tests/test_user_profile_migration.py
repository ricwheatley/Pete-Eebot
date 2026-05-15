from __future__ import annotations

from pathlib import Path


def test_profile_migration_defines_optional_profiles_and_assignments() -> None:
    migration = Path("migrations/20260515_add_user_profiles.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS user_profiles" in migration
    assert "slug TEXT NOT NULL UNIQUE" in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_user_profiles_single_default" in migration
    assert "CREATE TABLE IF NOT EXISTS auth_user_profiles" in migration
    assert "REFERENCES auth_users(id) ON DELETE CASCADE" in migration
    assert "REFERENCES user_profiles(id) ON DELETE CASCADE" in migration
    assert "INSERT INTO user_profiles (slug, display_name, timezone, is_default)" in migration


def test_bootstrap_schema_includes_profile_tables_for_new_databases() -> None:
    schema = Path("init-db/schema.sql").read_text(encoding="utf-8")

    for table_name in ("user_profiles", "auth_user_profiles"):
        assert f"DROP TABLE IF EXISTS {table_name} CASCADE" in schema
        assert f"CREATE TABLE {table_name}" in schema

    assert "CREATE UNIQUE INDEX ux_user_profiles_single_default" in schema
    assert "INSERT INTO user_profiles (slug, display_name, timezone, is_default)" in schema
