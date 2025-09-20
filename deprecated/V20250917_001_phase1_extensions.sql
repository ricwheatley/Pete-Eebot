BEGIN;

-- 1A) Planning period bookkeeping - blocks
CREATE TABLE IF NOT EXISTS training_blocks (
    id           SERIAL PRIMARY KEY,
    start_date   DATE NOT NULL,
    end_date     DATE NOT NULL,
    block_index  INT  NOT NULL,  -- running index across blocks
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_training_blocks_start ON training_blocks(start_date);
CREATE INDEX IF NOT EXISTS idx_training_blocks_end   ON training_blocks(end_date);

COMMENT ON TABLE training_blocks IS 'Logical 4-week blocks that group a training_plan lifecycle.';

-- 1B) Training max storage for strength test weeks
CREATE TABLE IF NOT EXISTS training_max (
    id           SERIAL PRIMARY KEY,
    lift_code    TEXT NOT NULL,           -- e.g. squat, bench, deadlift, ohp
    tm_kg        NUMERIC(6,2) NOT NULL,   -- current training max in kg
    source       TEXT NOT NULL,           -- e.g. AMRAP_EPLEY, MANUAL
    measured_at  DATE NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_training_max_lift_measured ON training_max(lift_code, measured_at);

COMMENT ON TABLE training_max IS 'Training max history per main lift, updated by quarterly AMRAP test weeks.';

-- 1C) Extend training_plan_workouts to support percentages, targets, timing and cardio
ALTER TABLE training_plan_workouts
    ADD COLUMN IF NOT EXISTS percent_1rm       NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS target_weight_kg  NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS rir_cue           NUMERIC(3,1),
    ADD COLUMN IF NOT EXISTS scheduled_time    TIME,
    ADD COLUMN IF NOT EXISTS is_cardio         BOOLEAN NOT NULL DEFAULT false;

-- Helpful indexes for scheduling and export queries
CREATE INDEX IF NOT EXISTS idx_tpw_week_day     ON training_plan_workouts(week_id, day_of_week);
CREATE INDEX IF NOT EXISTS idx_tpw_is_cardio    ON training_plan_workouts(is_cardio);
CREATE INDEX IF NOT EXISTS idx_tpw_exercise     ON training_plan_workouts(exercise_id);

COMMENT ON COLUMN training_plan_workouts.percent_1rm      IS 'Main lift prescription in percent of 1RM for this workout.';
COMMENT ON COLUMN training_plan_workouts.target_weight_kg IS 'Target working weight in kg for this exercise where applicable.';
COMMENT ON COLUMN training_plan_workouts.rir_cue          IS 'Target Reps-In-Reserve cue for lifter awareness.';
COMMENT ON COLUMN training_plan_workouts.scheduled_time   IS 'Planned time of day for the session, scheduled around Blaze.';
COMMENT ON COLUMN training_plan_workouts.is_cardio        IS 'True for Blaze or other cardio entries.';

-- 1D) Idempotent export logging for Wger
CREATE TABLE IF NOT EXISTS wger_export_log (
    id             BIGSERIAL PRIMARY KEY,
    plan_id        INT NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
    week_number    INT NOT NULL,
    payload_json   JSONB NOT NULL,
    response_json  JSONB,
    checksum       TEXT NOT NULL,  -- hash of plan_id + week_number + payload
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_id, week_number, checksum)
);
CREATE INDEX IF NOT EXISTS idx_wger_export_log_created  ON wger_export_log(created_at DESC);

COMMENT ON TABLE wger_export_log IS 'Audit of week-level Wger exports with idempotency checksum.';

-- 1E) Upgrade planned muscle volume MV to use real kg where available
-- Old MV used sets*reps and a 1.0/0.5 primary/secondary weighting, labelled as kg.
-- We now multiply by COALESCE(target_weight_kg, 1) to express planned volume in kg.
DROP MATERIALIZED VIEW IF EXISTS plan_muscle_volume;

CREATE MATERIALIZED VIEW plan_muscle_volume AS
SELECT
    tp.id AS plan_id,
    tw.week_number,
    m.id AS muscle_id,
    SUM(
        tpw.sets * tpw.reps
        * COALESCE(tpw.target_weight_kg, 1)
        * CASE WHEN p.muscle_id IS NOT NULL THEN 1.0 ELSE 0.5 END
    ) AS target_volume_kg
FROM training_plan_workouts tpw
JOIN training_plan_weeks   tw ON tpw.week_id = tw.id
JOIN training_plans        tp ON tw.plan_id = tp.id
JOIN wger_exercise          e ON tpw.exercise_id = e.id
LEFT JOIN wger_exercise_muscle_primary   p ON e.id = p.exercise_id
LEFT JOIN wger_exercise_muscle_secondary s ON e.id = s.exercise_id
LEFT JOIN wger_muscle                    m ON m.id = COALESCE(p.muscle_id, s.muscle_id)
GROUP BY tp.id, tw.week_number, m.id;

COMMENT ON MATERIALIZED VIEW plan_muscle_volume IS 'Planned weekly muscle-group volume in kg, primary weighted 1.0, secondary 0.5.';

-- Keep actual_muscle_volume as-is. It already computes reps*weight_kg and the same weighting.
-- Optionally refresh both MVs once, outside of transaction, after you populate target_weight_kg.

-- 1F) Privileges remain the same as baseline; re-apply for new objects
GRANT ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public TO pete_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO pete_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO pete_user;

COMMIT;
