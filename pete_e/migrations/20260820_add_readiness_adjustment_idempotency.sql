-- The authoritative migration runner owns the transaction boundary.

ALTER TABLE training_plan_workouts
    ADD COLUMN IF NOT EXISTS baseline_sets INT,
    ADD COLUMN IF NOT EXISTS baseline_rir FLOAT;

-- Existing installations cannot reconstruct prescriptions that were adjusted
-- before this migration. Preserve their current state as the initial baseline.
UPDATE training_plan_workouts
SET baseline_sets = sets
WHERE baseline_sets IS NULL;

UPDATE training_plan_workouts
SET baseline_rir = rir
WHERE baseline_rir IS NULL AND rir IS NOT NULL;

ALTER TABLE training_plan_workouts
    ALTER COLUMN baseline_sets SET NOT NULL;

-- Zero-set rows are valid legacy/comment-only placeholders. They are not
-- adjustable exercise prescriptions, but their immutable baseline must still
-- be preserved. Negative prescriptions remain invalid.
ALTER TABLE training_plan_workouts
    DROP CONSTRAINT IF EXISTS training_plan_workouts_baseline_sets_positive;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'training_plan_workouts_baseline_sets_nonnegative'
          AND conrelid = 'training_plan_workouts'::regclass
    ) THEN
        ALTER TABLE training_plan_workouts
            ADD CONSTRAINT training_plan_workouts_baseline_sets_nonnegative
            CHECK (baseline_sets >= 0) NOT VALID;
    END IF;
END $$;

ALTER TABLE training_plan_workouts
    VALIDATE CONSTRAINT training_plan_workouts_baseline_sets_nonnegative;

COMMENT ON COLUMN training_plan_workouts.baseline_sets IS
    'Canonical prescribed set count; readiness application never mutates this value.';
COMMENT ON COLUMN training_plan_workouts.sets IS
    'Effective set count consumed by plan reads and exports; derived from baseline_sets.';
COMMENT ON COLUMN training_plan_workouts.baseline_rir IS
    'Canonical prescribed RIR; readiness application never mutates this value.';
COMMENT ON COLUMN training_plan_workouts.rir IS
    'Effective RIR consumed by plan reads and exports; derived from baseline_rir.';

CREATE TABLE IF NOT EXISTS plan_readiness_adjustments (
    id BIGSERIAL PRIMARY KEY,
    plan_id INT NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
    week_id INT NOT NULL REFERENCES training_plan_weeks(id) ON DELETE CASCADE,
    week_number INT NOT NULL CHECK (week_number >= 1),
    week_start_date DATE NOT NULL,
    policy_version TEXT NOT NULL,
    source_data_hash CHAR(64) NOT NULL,
    baseline_prescription_hash CHAR(64) NOT NULL,
    set_multiplier NUMERIC(6,4) NOT NULL CHECK (set_multiplier > 0),
    rir_increment INT NOT NULL,
    source_summary JSONB NOT NULL,
    decision_json JSONB NOT NULL,
    result_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_plan_readiness_adjustment_identity UNIQUE (
        plan_id,
        week_id,
        policy_version,
        source_data_hash,
        baseline_prescription_hash
    )
);

ALTER TABLE training_plan_weeks
    ADD COLUMN IF NOT EXISTS effective_readiness_adjustment_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'training_plan_weeks_effective_readiness_adjustment_fk'
          AND conrelid = 'training_plan_weeks'::regclass
    ) THEN
        ALTER TABLE training_plan_weeks
            ADD CONSTRAINT training_plan_weeks_effective_readiness_adjustment_fk
            FOREIGN KEY (effective_readiness_adjustment_id)
            REFERENCES plan_readiness_adjustments(id)
            ON DELETE SET NULL;
    END IF;
END $$;

COMMENT ON TABLE plan_readiness_adjustments IS
    'Durable audit ledger for readiness decisions applied idempotently to plan-week baselines.';
COMMENT ON COLUMN training_plan_weeks.effective_readiness_adjustment_id IS
    'Readiness ledger row that currently defines this week effective strength prescription.';
