from __future__ import annotations

from pathlib import Path


MIGRATION = Path("pete_e/migrations/20260820_add_readiness_adjustment_idempotency.sql")


def test_authoritative_migration_distinguishes_baseline_and_effective_prescriptions() -> None:
    schema = MIGRATION.read_text(encoding="utf-8")

    assert "ALTER COLUMN baseline_sets SET NOT NULL" in schema
    assert "training_plan_workouts_baseline_sets_nonnegative" in schema
    assert "CHECK (baseline_sets >= 0)" in schema
    assert "baseline_rir FLOAT" in schema
    assert "CREATE TABLE IF NOT EXISTS plan_readiness_adjustments" in schema
    assert "effective_readiness_adjustment_id" in schema
    assert "ux_plan_readiness_adjustment_identity" in schema


def test_readiness_migration_backfills_baselines_and_enforces_identity() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "SET baseline_sets = sets" in migration
    assert "SET baseline_rir = rir" in migration
    assert "training_plan_workouts_baseline_sets_nonnegative" in migration
    assert "CHECK (baseline_sets >= 0) NOT VALID" in migration
    assert "CREATE TABLE IF NOT EXISTS plan_readiness_adjustments" in migration
    assert "source_data_hash CHAR(64) NOT NULL" in migration
    assert "baseline_prescription_hash CHAR(64) NOT NULL" in migration
    assert "CONSTRAINT ux_plan_readiness_adjustment_identity UNIQUE" in migration
    assert "training_plan_weeks_effective_readiness_adjustment_fk" in migration
