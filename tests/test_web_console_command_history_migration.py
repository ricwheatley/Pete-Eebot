from __future__ import annotations

from pathlib import Path


def test_web_console_jobs_migration_defines_command_history_storage() -> None:
    migration = Path("migrations/20260515_add_web_console_jobs.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS application_jobs" in migration
    assert "ADD COLUMN IF NOT EXISTS auth_scheme TEXT" in migration
    assert "CREATE TABLE IF NOT EXISTS web_console_command_history" in migration
    assert "request_id TEXT NOT NULL" in migration
    assert "job_id TEXT REFERENCES application_jobs(id) ON DELETE SET NULL" in migration
    assert "auth_scheme TEXT" in migration
    assert "command TEXT NOT NULL" in migration
    assert "outcome TEXT NOT NULL" in migration
    assert "safe_summary JSONB NOT NULL DEFAULT '{}'::jsonb" in migration
    assert "idx_web_console_command_history_command_outcome" in migration


def test_bootstrap_schema_includes_web_console_command_history_tables() -> None:
    schema = Path("init-db/schema.sql").read_text(encoding="utf-8")

    assert "DROP TABLE IF EXISTS web_console_command_history CASCADE" in schema
    assert "CREATE TABLE web_console_command_history" in schema
    assert "auth_scheme TEXT" in schema
    assert "CREATE INDEX idx_web_console_command_history_job_id" in schema
