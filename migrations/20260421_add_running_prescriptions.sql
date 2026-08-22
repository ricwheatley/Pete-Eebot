-- The authoritative migration runner owns the transaction boundary.

ALTER TABLE training_plan_workouts
    ADD COLUMN IF NOT EXISTS comment TEXT,
    ADD COLUMN IF NOT EXISTS optional BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS recovery_focused BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS details JSONB;
