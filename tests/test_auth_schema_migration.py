from __future__ import annotations

from pathlib import Path


def test_auth_migration_defines_users_sessions_and_rbac_roles() -> None:
    migration = Path("migrations/20260515_add_auth_users_sessions_rbac.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS auth_roles" in migration
    assert "('owner'" in migration
    assert "('operator'" in migration
    assert "('read_only'" in migration
    assert "CREATE TABLE IF NOT EXISTS auth_users" in migration
    assert "password_hash TEXT NOT NULL" in migration
    assert "CREATE TABLE IF NOT EXISTS auth_user_roles" in migration
    assert "CREATE TABLE IF NOT EXISTS auth_sessions" in migration
    assert "token_hash CHAR(64) NOT NULL UNIQUE" in migration


def test_bootstrap_schema_includes_auth_tables_for_new_databases() -> None:
    schema = Path("init-db/schema.sql").read_text(encoding="utf-8")

    for table_name in ("auth_roles", "auth_users", "auth_user_roles", "auth_sessions"):
        assert f"DROP TABLE IF EXISTS {table_name} CASCADE" in schema
        assert f"CREATE TABLE {table_name}" in schema
