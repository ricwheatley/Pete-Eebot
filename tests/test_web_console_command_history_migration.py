from __future__ import annotations

from pathlib import Path


def _table_block(sql: str, table_name: str) -> str:
    start = sql.index(f"CREATE TABLE")
    table_start = sql.index(table_name, start)
    return sql[table_start: sql.index(");", table_start)]


def test_web_console_jobs_migration_defines_command_history_storage() -> None:
    migration = Path("migrations/20260515_add_web_console_jobs.sql").read_text(encoding="utf-8")
    command_history = _table_block(migration, "web_console_command_history")

    assert "CREATE TABLE IF NOT EXISTS application_jobs" in migration
    assert "ADD COLUMN IF NOT EXISTS auth_scheme TEXT" in migration
    assert "CREATE TABLE IF NOT EXISTS web_console_command_history" in migration
    assert "request_id TEXT NOT NULL" in command_history
    assert "job_id TEXT" in command_history
    assert "job_id TEXT REFERENCES application_jobs(id) ON DELETE SET NULL" not in command_history
    assert "auth_scheme TEXT" in command_history
    assert "command TEXT NOT NULL" in command_history
    assert "outcome TEXT NOT NULL" in command_history
    assert "safe_summary JSONB NOT NULL DEFAULT '{}'::jsonb" in command_history
    assert "idx_web_console_command_history_command_outcome" in migration


def test_bootstrap_schema_includes_web_console_command_history_tables() -> None:
    schema = Path("init-db/schema.sql").read_text(encoding="utf-8")
    command_history = _table_block(schema, "web_console_command_history")

    assert "DROP TABLE IF EXISTS web_console_command_history CASCADE" in schema
    assert "CREATE TABLE web_console_command_history" in schema
    assert "job_id TEXT REFERENCES application_jobs(id) ON DELETE SET NULL" not in command_history
    assert "auth_scheme TEXT" in command_history
    assert "CREATE INDEX idx_web_console_command_history_job_id" in schema


def test_command_history_job_fk_relaxation_migration_drops_blocking_constraint() -> None:
    migration = Path("migrations/20260610_relax_command_history_job_fk.sql").read_text(encoding="utf-8")

    assert "ALTER TABLE IF EXISTS web_console_command_history" in migration
    assert "DROP CONSTRAINT IF EXISTS web_console_command_history_job_id_fkey" in migration
