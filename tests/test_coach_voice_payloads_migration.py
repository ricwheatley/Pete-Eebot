from pathlib import Path


def test_coach_voice_payloads_migration_defines_full_payload_audit_table() -> None:
    migration = Path("migrations/20260610_add_coach_voice_payloads.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS coach_voice_payloads" in migration
    assert "request_payload JSONB NOT NULL" in migration
    assert "prompt_messages JSONB NOT NULL" in migration
    assert "fallback_text TEXT NOT NULL" in migration
    assert "final_text TEXT NOT NULL" in migration
    assert "idx_coach_voice_payloads_message_type_created_at" in migration


def test_bootstrap_schema_includes_coach_voice_payloads_table() -> None:
    schema = Path("init-db/schema.sql").read_text(encoding="utf-8")

    assert "DROP TABLE IF EXISTS coach_voice_payloads CASCADE" in schema
    assert "CREATE TABLE coach_voice_payloads" in schema
    assert "request_payload JSONB NOT NULL" in schema
    assert "CREATE INDEX idx_coach_voice_payloads_status_created_at" in schema
