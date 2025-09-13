-- =============================================================================
-- Pete-Eebot PostgreSQL Schema
-- Version 1.1
--
-- This script defines the complete relational schema for the Pete-Eebot
-- personal data warehouse. It is designed based on the raw JSON data from
-- Withings, Apple Health, and the full Wger exercise catalog.
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
-- Purpose: Central fact table holding one record per day for all single-value
--          metrics from various sources.
-- -----------------------------------------------------------------------------
CREATE TABLE daily_summary (
    "date" DATE PRIMARY KEY,

    -- Withings Body Metrics
    weight_kg NUMERIC(5, 2),
    body_fat_pct NUMERIC(4, 2),

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

    -- Apple Health Sleep Metrics
    sleep_asleep_minutes INTEGER,
    sleep_details JSONB
);

COMMENT ON TABLE daily_summary IS 'Central table for daily aggregated health and fitness metrics.';


-- =============================================================================
-- WGER EXERCISE CATALOG TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Table: wger_category
-- Purpose: Dimension table for wger exercise categories (e.g., Arms, Legs).
-- -----------------------------------------------------------------------------
CREATE TABLE wger_category (
    id INTEGER PRIMARY KEY,
    "name" VARCHAR(100) NOT NULL
);
COMMENT ON TABLE wger_category IS 'Dimension table for Wger exercise categories.';

-- -----------------------------------------------------------------------------
-- Table: wger_equipment
-- Purpose: Dimension table for wger equipment (e.g., Barbell, Dumbbell).
-- -----------------------------------------------------------------------------
CREATE TABLE wger_equipment (
    id INTEGER PRIMARY KEY,
    "name" VARCHAR(100) NOT NULL
);
COMMENT ON TABLE wger_equipment IS 'Dimension table for Wger equipment types.';

-- -----------------------------------------------------------------------------
-- Table: wger_muscle
-- Purpose: Dimension table for wger muscles (e.g., Biceps brachii).
-- -----------------------------------------------------------------------------
CREATE TABLE wger_muscle (
    id INTEGER PRIMARY KEY,
    "name" VARCHAR(100) NOT NULL,
    name_en VARCHAR(100),
    is_front BOOLEAN NOT NULL
);
COMMENT ON TABLE wger_muscle IS 'Dimension table for Wger muscles.';

-- -----------------------------------------------------------------------------
-- Table: wger_exercise
-- Purpose: Main dimension table for all exercises from the Wger catalog.
-- -----------------------------------------------------------------------------
CREATE TABLE wger_exercise (
    id INTEGER PRIMARY KEY,
    uuid UUID NOT NULL UNIQUE,
    "name" VARCHAR(255) NOT NULL,
    description TEXT,
    category_id INTEGER REFERENCES wger_category(id)
);
COMMENT ON TABLE wger_exercise IS 'Main dimension table for all Wger exercises.';

-- -----------------------------------------------------------------------------
-- Junction Tables for Many-to-Many Relationships
-- -----------------------------------------------------------------------------

CREATE TABLE wger_exercise_equipment (
    exercise_id INTEGER REFERENCES wger_exercise(id) ON DELETE CASCADE,
    equipment_id INTEGER REFERENCES wger_equipment(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, equipment_id)
);
COMMENT ON TABLE wger_exercise_equipment IS 'Junction table linking exercises to the equipment they require.';

CREATE TABLE wger_exercise_muscle_primary (
    exercise_id INTEGER REFERENCES wger_exercise(id) ON DELETE CASCADE,
    muscle_id INTEGER REFERENCES wger_muscle(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, muscle_id)
);
COMMENT ON TABLE wger_exercise_muscle_primary IS 'Junction table linking exercises to their primary muscles.';

CREATE TABLE wger_exercise_muscle_secondary (
    exercise_id INTEGER REFERENCES wger_exercise(id) ON DELETE CASCADE,
    muscle_id INTEGER REFERENCES wger_muscle(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, muscle_id)
);
COMMENT ON TABLE wger_exercise_muscle_secondary IS 'Junction table linking exercises to their secondary muscles.';


-- =============================================================================
-- DATA LOGGING TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Table: strength_log
-- Purpose: Fact table to store individual strength training sets.
-- -----------------------------------------------------------------------------
CREATE TABLE strength_log (
    id BIGINT PRIMARY KEY,
    summary_date DATE NOT NULL REFERENCES daily_summary(date) ON DELETE CASCADE,
    exercise_id INTEGER NOT NULL REFERENCES wger_exercise(id),
    
    -- Performance Metrics
    reps INTEGER,
    weight_kg NUMERIC(6, 2),
    rir NUMERIC(3, 1),

    -- Wger specific metadata
    wger_session_id INTEGER
);

CREATE INDEX idx_strength_log_summary_date ON strength_log(summary_date);
CREATE INDEX idx_strength_log_exercise_id ON strength_log(exercise_id);

COMMENT ON TABLE strength_log IS 'Stores individual sets from strength training workouts.';

-- =============================================================================
-- End of Schema
-- =============================================================================

