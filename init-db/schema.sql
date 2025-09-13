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
DROP TABLE IF EXISTS strength_log;
DROP TABLE IF EXISTS wger_exercise_muscle_secondary;
DROP TABLE IF EXISTS wger_exercise_muscle_primary;
DROP TABLE IF EXISTS wger_exercise_equipment;
DROP TABLE IF EXISTS wger_exercise;
DROP TABLE IF EXISTS wger_muscle;
DROP TABLE IF EXISTS wger_equipment;
DROP TABLE IF EXISTS wger_category;
DROP TABLE IF EXISTS daily_summary;


-- -----------------------------------------------------------------------------
-- Table: daily_summary
-- -----------------------------------------------------------------------------
CREATE TABLE daily_summary (
    summary_date DATE PRIMARY KEY,

    -- Withings Body Metrics
    weight_kg NUMERIC(5, 2),
    body_fat_pct NUMERIC(4, 2),
    muscle_mass_kg NUMERIC(5, 2),
    water_pct NUMERIC(4, 2),

    -- Apple Health Activity Metrics
    steps INTEGER,
    exercise_minutes INTEGER,
    calories_active INTEGER,
    calories_resting INTEGER,
    stand_minutes INTEGER,
    distance_m INTEGER,

    -- Apple Health Heart Rate Metrics
    hr_resting INTEGER,
    hr_avg INTEGER,
    hr_max INTEGER,
    hr_min INTEGER,

    -- Apple Health Sleep Metrics (Flattened)
    sleep_total_minutes INTEGER,
    sleep_asleep_minutes INTEGER,
    sleep_rem_minutes INTEGER,
    sleep_deep_minutes INTEGER,
    sleep_core_minutes INTEGER,
    sleep_awake_minutes INTEGER
);

COMMENT ON TABLE daily_summary IS 'Central table for daily aggregated health and fitness metrics.';


-- =============================================================================
-- WGER EXERCISE CATALOG TABLES
-- =============================================================================

CREATE TABLE wger_category (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

CREATE TABLE wger_equipment (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

CREATE TABLE wger_muscle (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    name_en VARCHAR(100),
    is_front BOOLEAN NOT NULL
);

CREATE TABLE wger_exercise (
    id INTEGER PRIMARY KEY,
    uuid UUID NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category_id INTEGER REFERENCES wger_category(id)
);

-- Junction Tables
CREATE TABLE wger_exercise_equipment (
    exercise_id INTEGER REFERENCES wger_exercise(id) ON DELETE CASCADE,
    equipment_id INTEGER REFERENCES wger_equipment(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, equipment_id)
);

CREATE TABLE wger_exercise_muscle_primary (
    exercise_id INTEGER REFERENCES wger_exercise(id) ON DELETE CASCADE,
    muscle_id INTEGER REFERENCES wger_muscle(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, muscle_id)
);

CREATE TABLE wger_exercise_muscle_secondary (
    exercise_id INTEGER REFERENCES wger_exercise(id) ON DELETE CASCADE,
    muscle_id INTEGER REFERENCES wger_muscle(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, muscle_id)
);

-- =============================================================================
-- DATA LOGGING TABLES
-- =============================================================================

CREATE TABLE strength_log (
    id SERIAL PRIMARY KEY,
    summary_date DATE NOT NULL REFERENCES daily_summary(summary_date) ON DELETE CASCADE,
    exercise_id INTEGER NOT NULL REFERENCES wger_exercise(id),
    reps INTEGER,
    weight_kg NUMERIC(6, 2),
    rir NUMERIC(3, 1)
);

CREATE INDEX idx_strength_log_summary_date ON strength_log(summary_date);
CREATE INDEX idx_strength_log_exercise_id ON strength_log(exercise_id);

COMMENT ON TABLE strength_log IS 'Stores individual sets from strength training workouts.';

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO pete_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO pete_user;

-- -----------------------------------------------------------------------------
-- Table: training_plans
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS training_plans (
    id SERIAL PRIMARY KEY,
    start_date DATE UNIQUE NOT NULL,
    plan JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_training_plans_start_date ON training_plans(start_date);