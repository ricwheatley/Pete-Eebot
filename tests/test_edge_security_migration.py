from pathlib import Path


def test_public_edge_trust_migration_adds_durable_limits_and_delivery_uniqueness() -> None:
    migration = Path("pete_e/migrations/20260822_trust_public_edge.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE edge_rate_limit_counters" in migration
    assert "PRIMARY KEY (scope, subject_hash)" in migration
    assert "CREATE TABLE github_webhook_deliveries" in migration
    assert "delivery_id TEXT PRIMARY KEY" in migration
    assert "job_id TEXT NOT NULL UNIQUE" in migration
    assert "uq_github_signed_deploy_event UNIQUE" in migration
    assert "DROP TABLE" not in migration
