-- =============================================================================
-- Pete-Eebot PostgreSQL Schema
-- Version 1.3 (Corrected)
--
-- This script defines the complete relational schema for the Pete-Eebot
-- personal data warehouse.
-- Changelog:
--  - Flattened sleep data into individual columns for easier querying.
-- =============================================================================


-- Drop tables in reverse order of dependency to avoid foreign key errors
DROP TABLE IF EXISTS withings_daily CASCADE;
DROP TABLE IF EXISTS apple_daily CASCADE;
DROP TABLE IF EXISTS wger_exercise_muscle_secondary CASCADE;
DROP TABLE IF EXISTS wger_exercise_muscle_primary CASCADE;
DROP TABLE IF EXISTS wger_exercise_equipment CASCADE;
DROP TABLE IF EXISTS wger_exercise CASCADE;
DROP TABLE IF EXISTS wger_muscle CASCADE;
DROP TABLE IF EXISTS wger_equipment CASCADE;
DROP TABLE IF EXISTS wger_category CASCADE;
DROP TABLE IF EXISTS wger_logs CASCADE;
DROP TABLE IF EXISTS body_age_daily CASCADE;
DROP TABLE IF EXISTS training_plans CASCADE;
DROP TABLE IF EXISTS training_plan_weeks CASCADE;
DROP TABLE IF EXISTS training_plan_workouts CASCADE;
DROP VIEW IF EXISTS daily_summary;
DROP MATERIALIZED VIEW IF EXISTS plan_muscle_volume;
DROP MATERIALIZED VIEW IF EXISTS actual_muscle_volume;


-- =============================================================================
-- WGER EXERCISE CATALOG TABLES
-- =============================================================================

CREATE TABLE wger_category (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);
COMMENT ON TABLE wger_category IS 'Stores exercise categories like Strength, Cardio, etc.';

CREATE TABLE wger_equipment (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);
COMMENT ON TABLE wger_equipment IS 'Stores types of equipment used in exercises.';

CREATE TABLE wger_muscle (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    name_en VARCHAR(100),
    is_front BOOLEAN NOT NULL
);
COMMENT ON TABLE wger_muscle IS 'Stores muscles targeted by exercises, with front/back indicator.';

CREATE TABLE wger_exercise (
    id INTEGER PRIMARY KEY,
    uuid UUID NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category_id INTEGER REFERENCES wger_category(id)
);
COMMENT ON TABLE wger_exercise IS 'Stores exercises with references to category, equipment, and muscles.';

-- Junction Tables
CREATE TABLE wger_exercise_equipment (
    exercise_id INTEGER REFERENCES wger_exercise(id) ON DELETE CASCADE,
    equipment_id INTEGER REFERENCES wger_equipment(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, equipment_id)
);
COMMENT ON TABLE wger_exercise_equipment IS 'Junction table linking exercises to required equipment.';

CREATE TABLE wger_exercise_muscle_primary (
    exercise_id INTEGER REFERENCES wger_exercise(id) ON DELETE CASCADE,
    muscle_id INTEGER REFERENCES wger_muscle(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, muscle_id)
);
COMMENT ON TABLE wger_exercise_muscle_primary IS 'Junction table linking exercises to primary muscles targeted.';

CREATE TABLE wger_exercise_muscle_secondary (
    exercise_id INTEGER REFERENCES wger_exercise(id) ON DELETE CASCADE,
    muscle_id INTEGER REFERENCES wger_muscle(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, muscle_id)
);
COMMENT ON TABLE wger_exercise_muscle_secondary IS 'Junction table linking exercises to secondary muscles targeted.';


-- =============================================================================
-- Raw Data Tables
-- =============================================================================
CREATE TABLE withings_daily (
    date DATE PRIMARY KEY,
    weight_kg NUMERIC(5,2),
    body_fat_pct NUMERIC(4,2)
);
CREATE INDEX idx_withings_daily_date ON withings_daily(date);
COMMENT ON TABLE withings_daily IS 'Stores daily body metrics from Withings devices.';


CREATE TABLE apple_daily (
    date DATE PRIMARY KEY,
    steps INT,
    exercise_minutes INT,
    calories_active INT,
    calories_resting INT,
    stand_minutes INT,
    distance_m NUMERIC,
    hr_resting NUMERIC,
    hr_avg NUMERIC,
    hr_max NUMERIC,
    hr_min NUMERIC,
    sleep_total_minutes INT,
    sleep_asleep_minutes INT,
    sleep_rem_minutes INT,
    sleep_deep_minutes INT,
    sleep_core_minutes INT,
    sleep_awake_minutes INT
);
CREATE INDEX idx_apple_daily_date ON apple_daily(date);
COMMENT ON TABLE apple_daily IS 'Stores daily activity, heart rate, and sleep metrics from Apple Health.';

CREATE TABLE wger_logs (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    exercise_id INT NOT NULL REFERENCES wger_exercise(id),
    set_number INT NOT NULL,
    reps INT NOT NULL,
    weight_kg NUMERIC,
    rir FLOAT,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(date, exercise_id, set_number)
);
CREATE INDEX idx_wger_logs_date ON wger_logs(date);
CREATE INDEX idx_wger_logs_exercise_id ON wger_logs(exercise_id);
COMMENT ON TABLE wger_logs IS 'Stores individual strength training sets logged via WGER.';


CREATE TABLE training_plans (
    id SERIAL PRIMARY KEY,
    start_date DATE NOT NULL,
    weeks INT NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX idx_training_plans_start_date ON training_plans(start_date);
COMMENT ON TABLE training_plans IS 'Stores training plans with start dates and durations.';

CREATE TABLE training_plan_weeks (
    id SERIAL PRIMARY KEY,
    plan_id INT REFERENCES training_plans(id) ON DELETE CASCADE,
    week_number INT NOT NULL
);
CREATE INDEX idx_training_plan_weeks_plan_id ON training_plan_weeks(plan_id);
COMMENT ON TABLE training_plan_weeks IS 'Stores individual weeks within a training plan.';

CREATE TABLE training_plan_workouts (
    id SERIAL PRIMARY KEY,
    week_id INT REFERENCES training_plan_weeks(id) ON DELETE CASCADE,
    day_of_week INT NOT NULL,  -- 1 = Mon … 7 = Sun
    exercise_id INT NOT NULL REFERENCES wger_exercise(id),
    sets INT NOT NULL,
    reps INT NOT NULL,
    rir FLOAT
);
CREATE INDEX idx_training_plan_workouts_week_id ON training_plan_workouts(week_id);
CREATE INDEX idx_training_plan_workouts_exercise_id ON training_plan_workouts(exercise_id);
COMMENT ON TABLE training_plan_workouts IS 'Stores individual workouts within a training plan week.';


-- =============================================================================
-- Views
-- =============================================================================

-- -----------------------------------------------------------------------------
-- View: daily_summary
-- -----------------------------------------------------------------------------
CREATE VIEW daily_summary AS
SELECT
    d.date,
    w.weight_kg,
    w.body_fat_pct,
    a.steps,
    a.exercise_minutes,
    a.calories_active,
    a.calories_resting,
    a.stand_minutes,
    a.distance_m,
    a.hr_resting,
    a.hr_avg,
    a.hr_max,
    a.hr_min,
    a.sleep_total_minutes,
    a.sleep_asleep_minutes,
    a.sleep_rem_minutes,
    a.sleep_deep_minutes,
    a.sleep_core_minutes,
    a.sleep_awake_minutes,
    b.body_age_years,
    b.body_age_delta_years,
    COALESCE(SUM(gl.weight_kg * gl.reps),0) AS strength_volume_kg
FROM generate_series(
    (SELECT MIN(date) FROM withings_daily),
    current_date,
    interval '1 day'
) d(date)
LEFT JOIN withings_daily w USING (date)
LEFT JOIN apple_daily a USING (date)
LEFT JOIN body_age_daily b USING (date)
LEFT JOIN wger_logs gl USING (date)
GROUP BY d.date, w.weight_kg, w.body_fat_pct,
         a.steps, a.exercise_minutes, a.calories_active, a.calories_resting,
         a.stand_minutes, a.distance_m, a.hr_resting, a.hr_avg, a.hr_max, a.hr_min,
         a.sleep_total_minutes, a.sleep_asleep_minutes, a.sleep_rem_minutes,
         a.sleep_deep_minutes, a.sleep_core_minutes, a.sleep_awake_minutes,
         b.body_age_years, b.body_age_delta_years;
COMMENT ON VIEW daily_summary IS 'Central view aggregating daily health and fitness metrics from various sources.';


-- -----------------------------------------------------------------------------
-- View: plan_muscle_volume
-- -----------------------------------------------------------------------------

CREATE MATERIALIZED VIEW plan_muscle_volume AS
SELECT
    tp.id AS plan_id,
    tw.week_number,
    m.id AS muscle_id,
    SUM(tpw.sets * tpw.reps *
        CASE WHEN p.muscle_id IS NOT NULL THEN 1.0 ELSE 0.5 END) AS target_volume_kg
FROM training_plan_workouts tpw
JOIN training_plan_weeks tw ON tpw.week_id = tw.id
JOIN training_plans tp ON tw.plan_id = tp.id
JOIN wger_exercise e ON tpw.exercise_id = e.id
LEFT JOIN wger_exercise_muscle_primary p ON e.id = p.exercise_id
LEFT JOIN wger_exercise_muscle_secondary s ON e.id = s.exercise_id
LEFT JOIN wger_muscle m ON m.id = COALESCE(p.muscle_id, s.muscle_id)
GROUP BY tp.id, tw.week_number, m.id;


-- -----------------------------------------------------------------------------
-- View: actual_muscle_volume
-- -----------------------------------------------------------------------------

CREATE MATERIALIZED VIEW actual_muscle_volume AS
SELECT
    gl.date,
    m.id AS muscle_id,
    SUM(gl.reps * COALESCE(gl.weight_kg,1) *
        CASE WHEN p.muscle_id IS NOT NULL THEN 1.0 ELSE 0.5 END) AS actual_volume_kg
FROM wger_logs gl
JOIN wger_exercise e ON gl.exercise_id = e.id
LEFT JOIN wger_exercise_muscle_primary p ON e.id = p.exercise_id
LEFT JOIN wger_exercise_muscle_secondary s ON e.id = s.exercise_id
LEFT JOIN wger_muscle m ON m.id = COALESCE(p.muscle_id, s.muscle_id)
GROUP BY gl.date, m.id;

-- -----------------------------------------------------------------------------
-- Grant privileges to pete_user
-- -----------------------------------------------------------------------------
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO pete_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO pete_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO pete_user;