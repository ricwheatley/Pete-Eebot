BEGIN;

-- Mark specific weeks as strength-test weeks
ALTER TABLE training_plan_weeks
    ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_training_plan_weeks_is_test
    ON training_plan_weeks(is_test);

-- Store lift-level results from a strength-test week (audit trail)
CREATE TABLE IF NOT EXISTS strength_test_result (
    id              BIGSERIAL PRIMARY KEY,
    plan_id         INT NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
    week_number     INT NOT NULL DEFAULT 1,
    lift_code       TEXT NOT NULL,         -- 'squat','bench','deadlift','ohp'
    test_date       DATE NOT NULL,          -- date of the AMRAP top set
    test_reps       INT NOT NULL,
    test_weight_kg  NUMERIC(6,2) NOT NULL,
    e1rm_kg         NUMERIC(6,2) NOT NULL,  -- Epley: w*(1 + reps/30)
    tm_kg           NUMERIC(6,2) NOT NULL,  -- 90% of e1RM, rounded in app
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_id, week_number, lift_code)
);

COMMIT;
