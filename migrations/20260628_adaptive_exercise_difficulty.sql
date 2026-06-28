BEGIN;

ALTER TABLE assistance_pool
    ADD COLUMN IF NOT EXISTS difficulty SMALLINT NOT NULL DEFAULT 5;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'assistance_pool_difficulty_range'
    ) THEN
        ALTER TABLE assistance_pool
            ADD CONSTRAINT assistance_pool_difficulty_range
            CHECK (difficulty BETWEEN 0 AND 10) NOT VALID;
    END IF;
END $$;

ALTER TABLE assistance_pool
    VALIDATE CONSTRAINT assistance_pool_difficulty_range;

CREATE TABLE IF NOT EXISTS core_pool (
    exercise_id INT PRIMARY KEY REFERENCES wger_exercise(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exercise_programming_metadata (
    exercise_id INT PRIMARY KEY REFERENCES wger_exercise(id) ON DELETE CASCADE,
    difficulty SMALLINT NOT NULL DEFAULT 0,
    eligible_core BOOLEAN NOT NULL DEFAULT false,
    eligible_bench_assistance BOOLEAN NOT NULL DEFAULT false,
    eligible_squat_assistance BOOLEAN NOT NULL DEFAULT false,
    eligible_ohp_assistance BOOLEAN NOT NULL DEFAULT false,
    eligible_deadlift_assistance BOOLEAN NOT NULL DEFAULT false,
    notes TEXT,
    metadata_source TEXT NOT NULL DEFAULT 'operator',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT exercise_programming_metadata_difficulty_range
        CHECK (difficulty BETWEEN 0 AND 10)
);

COMMENT ON TABLE exercise_programming_metadata IS
    'Pete-owned exercise programming metadata layered over the synced WGER catalogue.';
COMMENT ON COLUMN exercise_programming_metadata.difficulty IS
    '0 excludes the exercise from planning; 1-10 rates easiest to hardest.';

CREATE TABLE IF NOT EXISTS exercise_difficulty_unlock_state (
    scope TEXT PRIMARY KEY DEFAULT 'global',
    current_cap SMALLINT NOT NULL DEFAULT 2,
    last_evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_unlocked_at TIMESTAMPTZ,
    unlock_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT exercise_difficulty_unlock_scope_global
        CHECK (scope = 'global'),
    CONSTRAINT exercise_difficulty_unlock_cap_range
        CHECK (current_cap BETWEEN 1 AND 10)
);

INSERT INTO exercise_difficulty_unlock_state (scope, current_cap)
VALUES ('global', 2)
ON CONFLICT (scope) DO NOTHING;

ALTER TABLE training_plan_workouts
    ADD COLUMN IF NOT EXISTS programmed_difficulty SMALLINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'training_plan_workouts_programmed_difficulty_range'
    ) THEN
        ALTER TABLE training_plan_workouts
            ADD CONSTRAINT training_plan_workouts_programmed_difficulty_range
            CHECK (programmed_difficulty IS NULL OR programmed_difficulty BETWEEN 0 AND 10) NOT VALID;
    END IF;
END $$;

ALTER TABLE training_plan_workouts
    VALIDATE CONSTRAINT training_plan_workouts_programmed_difficulty_range;

WITH defaults(
    exercise_id,
    difficulty,
    eligible_core,
    eligible_bench_assistance,
    eligible_squat_assistance,
    eligible_ohp_assistance,
    eligible_deadlift_assistance,
    notes
) AS (
    VALUES
        (81, 2, false, true,  false, false, false, 'Seeded from curated bench assistance defaults.'),
        (76, 2, false, true,  false, false, false, 'Seeded from curated bench assistance defaults.'),
        (194, 4, false, true, false, false, false, 'Seeded from curated bench assistance defaults.'),
        (512, 0, false, false, false, false, false, 'Excluded cable/machine assistance default.'),
        (137, 0, false, false, false, false, false, 'Excluded machine assistance default.'),
        (43, 5, false, false, true,  false, false, 'Seeded from curated squat assistance defaults.'),
        (46, 2, false, false, true,  false, false, 'Seeded from curated squat assistance defaults.'),
        (373, 0, false, false, false, false, false, 'Excluded machine assistance default.'),
        (988, 3, false, false, true,  false, false, 'Seeded from curated squat assistance defaults.'),
        (1366, 2, false, false, true, false, false, 'Seeded from curated squat assistance defaults.'),
        (20, 2, false, false, false, true,  false, 'Seeded from curated OHP assistance defaults.'),
        (82, 2, false, false, false, true,  false, 'Seeded from curated OHP assistance defaults.'),
        (394, 0, false, false, false, false, false, 'Excluded cable/machine assistance default.'),
        (448, 4, false, false, false, true,  false, 'Seeded from curated OHP assistance defaults.'),
        (507, 3, false, false, false, false, true,  'Seeded from curated deadlift assistance defaults.'),
        (268, 4, false, false, false, false, true,  'Seeded from curated deadlift assistance defaults.'),
        (265, 1, false, false, false, false, true,  'Seeded from curated deadlift assistance defaults.'),
        (294, 2, false, false, false, false, true,  'Seeded from curated deadlift assistance defaults.'),
        (1348, 0, false, false, false, false, false, 'Excluded specialised bench/machine default.'),
        (458, 1, true, false, false, false, false, 'Seeded from curated core defaults.'),
        (1001, 1, true, false, false, false, false, 'Seeded from curated core defaults.'),
        (500, 2, true, false, false, false, false, 'Seeded from curated core defaults.'),
        (580, 2, true, false, false, false, false, 'Seeded from curated core defaults.'),
        (1410, 3, true, false, false, false, false, 'Seeded from curated core defaults.')
)
INSERT INTO exercise_programming_metadata (
    exercise_id,
    difficulty,
    eligible_core,
    eligible_bench_assistance,
    eligible_squat_assistance,
    eligible_ohp_assistance,
    eligible_deadlift_assistance,
    notes,
    metadata_source
)
SELECT
    defaults.exercise_id,
    defaults.difficulty,
    defaults.eligible_core,
    defaults.eligible_bench_assistance,
    defaults.eligible_squat_assistance,
    defaults.eligible_ohp_assistance,
    defaults.eligible_deadlift_assistance,
    defaults.notes,
    'seed'
FROM defaults
JOIN wger_exercise ex ON ex.id = defaults.exercise_id
ON CONFLICT (exercise_id) DO NOTHING;

INSERT INTO exercise_programming_metadata (exercise_id)
SELECT ex.id
FROM wger_exercise ex
ON CONFLICT (exercise_id) DO NOTHING;

CREATE OR REPLACE FUNCTION sp_plan_for_day(p_date DATE)
RETURNS TABLE (
    workout_date DATE,
    scheduled_time TIME,
    exercise_name TEXT,
    sets INT,
    reps INT,
    target_weight_kg NUMERIC,
    programmed_difficulty INT
) LANGUAGE sql AS $$
    SELECT p_date::date AS workout_date,
           tpw.scheduled_time,
           COALESCE(tpw.details->>'display_name', NULLIF(tpw.comment, ''), e.name, 'Planned session') AS exercise_name,
           tpw.sets,
           tpw.reps,
           tpw.target_weight_kg,
           tpw.programmed_difficulty::int
    FROM training_plan_workouts tpw
    JOIN training_plan_weeks tw ON tpw.week_id = tw.id
    JOIN training_plans tp ON tw.plan_id = tp.id
    LEFT JOIN wger_exercise e ON tpw.exercise_id = e.id
    WHERE tp.is_active = TRUE
      AND tp.start_date <= p_date
      AND (tp.start_date + ((tw.week_number + 1) * 7)) > p_date
      AND tpw.day_of_week = extract(isodow from p_date);
$$;

CREATE OR REPLACE FUNCTION sp_plan_for_week(p_start_date DATE)
RETURNS TABLE (
    workout_date DATE,
    day_of_week INT,
    scheduled_time TIME,
    exercise_name TEXT,
    sets INT,
    reps INT,
    target_weight_kg NUMERIC,
    programmed_difficulty INT
) LANGUAGE sql AS $$
    SELECT (p_start_date + (tpw.day_of_week - 1))::date AS workout_date,
           tpw.day_of_week,
           tpw.scheduled_time,
           COALESCE(tpw.details->>'display_name', NULLIF(tpw.comment, ''), e.name, 'Planned session') AS exercise_name,
           tpw.sets,
           tpw.reps,
           tpw.target_weight_kg,
           tpw.programmed_difficulty::int
    FROM training_plan_workouts tpw
    JOIN training_plan_weeks tw ON tpw.week_id = tw.id
    JOIN training_plans tp ON tw.plan_id = tp.id
    LEFT JOIN wger_exercise e ON tpw.exercise_id = e.id
    WHERE tp.is_active = TRUE
      AND tp.start_date <= p_start_date
      AND (tp.start_date + ((tw.week_number + 1) * 7)) > p_start_date
    ORDER BY
        tpw.day_of_week,
        COALESCE((tpw.details ->> 'sequence_order')::int, CASE WHEN tpw.is_cardio THEN 15 ELSE 20 END),
        tpw.scheduled_time;
$$;

COMMIT;
