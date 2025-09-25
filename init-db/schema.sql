-- =============================================================================
-- Pete-Eebot PostgreSQL Schema
-- Version 3.0 (Apple Health Granular Integration)
--
-- This script defines the complete, up-to-date relational schema.
-- Major changes in this version:
--  - Replaced the wide 'apple_daily' table with a fully normalized schema
--    to support detailed daily JSON exports from HealthAutoExport.
--  - Introduced new tables: Device, MetricType, DailyMetric,
--    DailyHeartRateSummary, DailySleepSummary, and a suite of tables for
--    detailed workout logging (Workout, WorkoutType, etc.).
--  - Rewrote the 'daily_summary' materialized view to aggregate data from
--    these new normalized tables.
-- =============================================================================


-- Drop objects in reverse order of dependency to ensure a clean slate
DROP VIEW IF EXISTS metrics_overview;
DROP MATERIALIZED VIEW IF EXISTS daily_summary;
DROP MATERIALIZED VIEW IF EXISTS plan_muscle_volume;
DROP MATERIALIZED VIEW IF EXISTS actual_muscle_volume;
DROP TABLE IF EXISTS "ImportLog" CASCADE;
DROP TABLE IF EXISTS "WorkoutHeartRateRecovery" CASCADE;
DROP TABLE IF EXISTS "WorkoutActiveEnergy" CASCADE;
DROP TABLE IF EXISTS "WorkoutStepCount" CASCADE;
DROP TABLE IF EXISTS "WorkoutHeartRate" CASCADE;
DROP TABLE IF EXISTS "Workout" CASCADE;
DROP TABLE IF EXISTS "WorkoutType" CASCADE;
DROP TABLE IF EXISTS "DailySleepSummary" CASCADE;
DROP TABLE IF EXISTS "DailyHeartRateSummary" CASCADE;
DROP TABLE IF EXISTS "DailyMetric" CASCADE;
DROP TABLE IF EXISTS "MetricType" CASCADE;
DROP TABLE IF EXISTS "Device" CASCADE;
DROP TABLE IF EXISTS strength_test_result CASCADE;
DROP TABLE IF EXISTS training_max CASCADE;
DROP TABLE IF EXISTS training_blocks CASCADE;
DROP TABLE IF EXISTS wger_export_log CASCADE;
DROP TABLE IF EXISTS training_plan_workouts CASCADE;
DROP TABLE IF EXISTS training_plan_weeks CASCADE;
DROP TABLE IF EXISTS training_plans CASCADE;
DROP TABLE IF EXISTS wger_logs CASCADE;
DROP TABLE IF EXISTS body_age_daily CASCADE;
DROP TABLE IF EXISTS withings_daily CASCADE;
DROP TABLE IF EXISTS assistance_pool CASCADE;
DROP TABLE IF EXISTS wger_exercise_muscle_secondary CASCADE;
DROP TABLE IF EXISTS wger_exercise_muscle_primary CASCADE;
DROP TABLE IF EXISTS wger_exercise_equipment CASCADE;
DROP TABLE IF EXISTS wger_exercise CASCADE;
DROP TABLE IF EXISTS wger_muscle CASCADE;
DROP TABLE IF EXISTS wger_equipment CASCADE;
DROP TABLE IF EXISTS wger_category CASCADE;
DROP FUNCTION IF EXISTS sp_upsert_body_age(date, date);
DROP FUNCTION IF EXISTS sp_upsert_body_age_range(date, date, date);


-- =============================================================================
-- SECTION 1: CORE DATA & CATALOG TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- WGER EXERCISE & TRAINING CATALOG
-- (No changes in this version)
-- -----------------------------------------------------------------------------
CREATE TABLE wger_category (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);
COMMENT ON TABLE wger_category IS 'Stores exercise categories like Strength, Cardio, etc.';

CREATE TABLE wger_equipment (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);
COMMENT ON TABLE wger_equipment IS 'Stores types of equipment used in exercises.';

CREATE TABLE wger_muscle (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    name_en VARCHAR(100),
    is_front BOOLEAN NOT NULL
);
COMMENT ON TABLE wger_muscle IS 'Stores muscles targeted by exercises, with front/back indicator.';

CREATE TABLE wger_exercise (
    id INT PRIMARY KEY,
    uuid UUID NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_main_lift BOOLEAN NOT NULL DEFAULT false,
    category_id INT REFERENCES wger_category(id)
);
COMMENT ON TABLE wger_exercise IS 'Core exercise catalog, including main lifts and assistance work.';

CREATE TABLE wger_exercise_equipment (
    exercise_id INT REFERENCES wger_exercise(id) ON DELETE CASCADE,
    equipment_id INT REFERENCES wger_equipment(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, equipment_id)
);

CREATE TABLE wger_exercise_muscle_primary (
    exercise_id INT REFERENCES wger_exercise(id) ON DELETE CASCADE,
    muscle_id INT REFERENCES wger_muscle(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, muscle_id)
);

CREATE TABLE wger_exercise_muscle_secondary (
    exercise_id INT REFERENCES wger_exercise(id) ON DELETE CASCADE,
    muscle_id INT REFERENCES wger_muscle(id) ON DELETE CASCADE,
    PRIMARY KEY (exercise_id, muscle_id)
);

-- -----------------------------------------------------------------------------
-- APPLE HEALTH REFERENCE TABLES (NEW)
-- -----------------------------------------------------------------------------
CREATE TABLE "Device" (
    device_id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);
COMMENT ON TABLE "Device" IS 'Stores unique source devices from Apple Health (e.g., "Ric''s Apple Watch").';

CREATE TABLE "MetricType" (
    metric_id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    unit TEXT NOT NULL
);
COMMENT ON TABLE "MetricType" IS 'Catalog of distinct daily metrics from Apple Health (e.g., "step_count", "active_energy").';

CREATE TABLE "WorkoutType" (
    type_id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);
COMMENT ON TABLE "WorkoutType" IS 'Lookup table for workout activity types (e.g., "High Intensity Interval Training").';

-- -----------------------------------------------------------------------------
-- RAW DAILY METRICS & LOGS
-- -----------------------------------------------------------------------------
CREATE TABLE withings_daily (
    date DATE PRIMARY KEY,
    weight_kg NUMERIC(5,2),
    body_fat_pct NUMERIC(4,2),
    muscle_pct NUMERIC(4,2),
    water_pct NUMERIC(4,2)
);
COMMENT ON TABLE withings_daily IS 'Stores daily body metrics from Withings. Source of truth for weight/bodyfat.';

-- NEW Apple Health Daily Metrics Tables (Normalized)
CREATE TABLE "DailyMetric" (
    metric_id INT NOT NULL REFERENCES "MetricType"(metric_id),
    device_id INT NOT NULL REFERENCES "Device"(device_id),
    date TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (metric_id, device_id, date)
);

-- The indexes should also be updated
CREATE INDEX idx_dailymetric_date ON "DailyMetric"(date);
CREATE INDEX idx_dailymetric_metric_date ON "DailyMetric"(metric_id, date);

CREATE TABLE "DailyHeartRateSummary" (
    device_id INT NOT NULL REFERENCES "Device"(device_id),
    date DATE NOT NULL,
    hr_min SMALLINT NOT NULL,
    hr_avg REAL NOT NULL,
    hr_max SMALLINT NOT NULL,
    PRIMARY KEY (device_id, date)
);
COMMENT ON TABLE "DailyHeartRateSummary" IS 'Stores daily min, average, and max heart rate summaries from Apple Health.';
CREATE INDEX idx_dailyhr_date ON "DailyHeartRateSummary"(date);

CREATE TABLE "DailySleepSummary" (
    device_id INT NOT NULL REFERENCES "Device"(device_id),
    date DATE NOT NULL,
    sleep_start TIMESTAMP NOT NULL,
    sleep_end TIMESTAMP NOT NULL,
    in_bed_start TIMESTAMP,
    in_bed_end TIMESTAMP,
    total_sleep_hrs NUMERIC(5,2) NOT NULL,
    core_hrs NUMERIC(5,2) NOT NULL,
    deep_hrs NUMERIC(5,2) NOT NULL,
    rem_hrs NUMERIC(5,2) NOT NULL,
    awake_hrs NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (device_id, date),
    CHECK (sleep_end > sleep_start)
);
COMMENT ON TABLE "DailySleepSummary" IS 'Stores detailed nightly sleep phase data from Apple Health for the morning date.';
CREATE INDEX idx_dailysleep_date ON "DailySleepSummary"(date);

-- WGER & Body Age Tables
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
COMMENT ON TABLE wger_logs IS 'Stores individual strength training sets. Source of truth for strength workouts.';

CREATE TABLE body_age_daily (
    date DATE PRIMARY KEY,
    input_window_days INT NOT NULL DEFAULT 7,
    crf_score NUMERIC(5,1),
    body_comp_score NUMERIC(5,1),
    activity_score NUMERIC(5,1),
    recovery_score NUMERIC(5,1),
    composite_score NUMERIC(5,1),
    body_age_years NUMERIC(6,1),
    age_delta_years NUMERIC(6,1),
    used_vo2max_direct BOOLEAN NOT NULL DEFAULT false,
    cap_minus_10_applied BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE body_age_daily IS 'Stores the daily calculated body age and its component scores.';

-- -----------------------------------------------------------------------------
-- DETAILED WORKOUT TABLES (NEW)
-- -----------------------------------------------------------------------------
CREATE TABLE "Workout" (
    workout_id UUID PRIMARY KEY,
    type_id INT NOT NULL REFERENCES "WorkoutType"(type_id),
    device_id INT NOT NULL REFERENCES "Device"(device_id),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    duration_sec NUMERIC(8,2) NOT NULL,
    location TEXT,
    total_distance_km NUMERIC(6,3),
    total_active_energy_kj NUMERIC(8,3),
    avg_intensity NUMERIC(5,2),
    elevation_gain_m NUMERIC(5,2),
    environment_temp_degc NUMERIC(5,2),
    environment_humidity_percent NUMERIC(5,2),
    CHECK (end_time > start_time)
);
COMMENT ON TABLE "Workout" IS 'Core table for each workout session, identified by Apple''s unique UUID.';
CREATE INDEX idx_workout_start_time ON "Workout"(start_time);

CREATE TABLE "WorkoutHeartRate" (
    workout_id UUID NOT NULL REFERENCES "Workout"(workout_id) ON DELETE CASCADE,
    offset_sec INT NOT NULL,
    hr_min SMALLINT NOT NULL,
    hr_avg REAL NOT NULL,
    hr_max SMALLINT NOT NULL,
    PRIMARY KEY (workout_id, offset_sec),
    CHECK (hr_min <= hr_avg AND hr_avg <= hr_max),
    CHECK (offset_sec >= 0)
);
COMMENT ON TABLE "WorkoutHeartRate" IS 'Stores time-series heart rate data (min/avg/max per interval) during a workout.';

CREATE TABLE "WorkoutStepCount" (
    workout_id UUID NOT NULL REFERENCES "Workout"(workout_id) ON DELETE CASCADE,
    offset_sec INT NOT NULL,
    steps REAL NOT NULL,
    PRIMARY KEY (workout_id, offset_sec),
    CHECK (offset_sec >= 0)
);

COMMENT ON TABLE "WorkoutStepCount" IS 'Stores time-series step count data recorded during a workout.';

CREATE TABLE "WorkoutActiveEnergy" (
    workout_id UUID NOT NULL REFERENCES "Workout"(workout_id) ON DELETE CASCADE,
    offset_sec INT NOT NULL,
    energy_kcal REAL NOT NULL,
    PRIMARY KEY (workout_id, offset_sec),
    CHECK (offset_sec >= 0)
);
COMMENT ON TABLE "WorkoutActiveEnergy" IS 'Stores time-series active energy (kcal) burned per interval during a workout.';

CREATE TABLE "WorkoutHeartRateRecovery" (
    workout_id UUID NOT NULL REFERENCES "Workout"(workout_id) ON DELETE CASCADE,
    offset_sec INT NOT NULL,
    hr_min SMALLINT NOT NULL,
    hr_avg SMALLINT NOT NULL,
    hr_max SMALLINT NOT NULL,
    PRIMARY KEY (workout_id, offset_sec),
    CHECK (offset_sec >= 0),
    CHECK (hr_min <= hr_avg AND hr_avg <= hr_max)
);
COMMENT ON TABLE "WorkoutHeartRateRecovery" IS 'Stores post-workout heart rate recovery readings at specific offsets.';

-- -----------------------------------------------------------------------------
-- TRAINING PLAN & LOGGING TABLES
-- (No changes in this version)
-- -----------------------------------------------------------------------------
CREATE TABLE training_blocks (
    id SERIAL PRIMARY KEY,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    block_index INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE training_plans (
    id SERIAL PRIMARY KEY,
    start_date DATE NOT NULL,
    weeks INT NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE training_plan_weeks (
    id SERIAL PRIMARY KEY,
    plan_id INT REFERENCES training_plans(id) ON DELETE CASCADE,
    week_number INT NOT NULL,
    is_test BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE training_plan_workouts (
    id SERIAL PRIMARY KEY,
    week_id INT REFERENCES training_plan_weeks(id) ON DELETE CASCADE,
    day_of_week INT NOT NULL,  -- 1 = Mon … 7 = Sun
    exercise_id INT NOT NULL REFERENCES wger_exercise(id),
    sets INT NOT NULL,
    reps INT NOT NULL,
    rir FLOAT,
    percent_1rm NUMERIC(5,2),
    target_weight_kg NUMERIC(6,2),
    rir_cue NUMERIC(3,1),
    scheduled_time TIME,
    is_cardio BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE assistance_pool (
    main_exercise_id INT NOT NULL REFERENCES wger_exercise(id) ON DELETE CASCADE,
    assistance_exercise_id INT NOT NULL REFERENCES wger_exercise(id) ON DELETE CASCADE,
    PRIMARY KEY(main_exercise_id, assistance_exercise_id)
);

CREATE TABLE training_max (
    id SERIAL PRIMARY KEY,
    lift_code TEXT NOT NULL,
    tm_kg NUMERIC(6,2) NOT NULL,
    source TEXT NOT NULL,
    measured_at DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (lift_code, measured_at)
);

CREATE TABLE strength_test_result (
    id BIGSERIAL PRIMARY KEY,
    plan_id INT NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
    week_number INT NOT NULL DEFAULT 1,
    lift_code TEXT NOT NULL,
    test_date DATE NOT NULL,
    test_reps INT NOT NULL,
    test_weight_kg NUMERIC(6,2) NOT NULL,
    e1rm_kg NUMERIC(6,2) NOT NULL,
    tm_kg NUMERIC(6,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_id, week_number, lift_code)
);

CREATE TABLE wger_export_log (
    id BIGSERIAL PRIMARY KEY,
    plan_id INT NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
    week_number INT NOT NULL,
    routine_id INT,
    payload_json JSONB NOT NULL,
    response_json JSONB,
    checksum TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_id, week_number, checksum)
);

-- =============================================================================
-- SECTION 2: MATERIALIZED VIEWS FOR ANALYSIS
-- =============================================================================

-- -----------------------------------------------------------------------------
-- MV: daily_summary (REWRITTEN)
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW daily_summary AS
WITH apple_metrics AS (
  SELECT
    dm.date,
    SUM(dm.value) FILTER (WHERE mt.name = 'step_count')                         AS steps,
    SUM(dm.value) FILTER (WHERE mt.name = 'apple_exercise_time')                AS exercise_minutes,
    SUM(dm.value) FILTER (WHERE mt.name = 'active_energy') * 0.239006           AS calories_active,
    SUM(dm.value) FILTER (WHERE mt.name = 'basal_energy_burned') * 0.239006     AS calories_resting,
    SUM(dm.value) FILTER (WHERE mt.name = 'apple_stand_time')                   AS stand_minutes,
    SUM(dm.value) FILTER (WHERE mt.name = 'distance_walking_running')           AS distance_m,
    AVG(dm.value) FILTER (WHERE mt.name = 'resting_heart_rate')                 AS hr_resting,
    AVG(dm.value) FILTER (WHERE mt.name = 'hrv_sdnn_ms')                        AS hrv_sdnn_ms,
    AVG(dm.value) FILTER (WHERE mt.name = 'vo2_max')                            AS vo2_max
  FROM "DailyMetric" dm
  JOIN "MetricType" mt ON dm.metric_id = mt.metric_id
  GROUP BY dm.date
),
dhr_agg AS (
  SELECT
    date,
    MIN(hr_min) AS hr_min,
    AVG(hr_avg) AS hr_avg,
    MAX(hr_max) AS hr_max
  FROM "DailyHeartRateSummary"
  GROUP BY date
),
dss_pick AS (
  -- pick the longest sleep episode per date
  SELECT DISTINCT ON (date)
    date,
    sleep_start, sleep_end, in_bed_start, in_bed_end,
    total_sleep_hrs, core_hrs, deep_hrs, rem_hrs, awake_hrs
  FROM "DailySleepSummary"
  ORDER BY date, total_sleep_hrs DESC
),
bounds AS (
  SELECT LEAST(
           COALESCE((SELECT MIN(date) FROM withings_daily), current_date),
           COALESCE((SELECT MIN(date) FROM "DailyMetric"), current_date),
           COALESCE((SELECT MIN(date) FROM "DailyHeartRateSummary"), current_date),
           COALESCE((SELECT MIN(date) FROM "DailySleepSummary"), current_date)
         ) AS start_date
)
SELECT
  d.date,
  w.weight_kg,
  w.body_fat_pct,
  w.muscle_pct,
  w.water_pct,
  am.steps,
  am.exercise_minutes,
  am.calories_active,
  am.calories_resting,
  am.stand_minutes,
  am.distance_m,
  am.hr_resting,
  am.hrv_sdnn_ms,
  am.vo2_max,
  dhr.hr_avg,
  dhr.hr_max,
  dhr.hr_min,
  dss.total_sleep_hrs * 60                                                        AS sleep_total_minutes,
  (dss.core_hrs + dss.deep_hrs + dss.rem_hrs) * 60                                AS sleep_asleep_minutes,
  dss.rem_hrs * 60                                                                AS sleep_rem_minutes,
  dss.deep_hrs * 60                                                               AS sleep_deep_minutes,
  dss.core_hrs * 60                                                               AS sleep_core_minutes,
  dss.awake_hrs * 60                                                              AS sleep_awake_minutes,
  b.body_age_years,
  b.age_delta_years                                                                AS body_age_delta_years,
  COALESCE(SUM(gl.weight_kg * gl.reps), 0)                                        AS strength_volume_kg
FROM generate_series((SELECT start_date FROM bounds), current_date, interval '1 day') AS d(date)
LEFT JOIN withings_daily w USING (date)
LEFT JOIN apple_metrics am USING (date)
LEFT JOIN dhr_agg dhr USING (date)
LEFT JOIN dss_pick dss USING (date)
LEFT JOIN body_age_daily b USING (date)
LEFT JOIN wger_logs gl USING (date)
GROUP BY
  d.date, w.weight_kg, w.body_fat_pct, w.muscle_pct, w.water_pct,
  am.steps, am.exercise_minutes, am.calories_active, am.calories_resting, am.stand_minutes, am.distance_m, am.hr_resting, am.hrv_sdnn_ms, am.vo2_max,
  dhr.hr_avg, dhr.hr_max, dhr.hr_min,
  dss.total_sleep_hrs, dss.core_hrs, dss.deep_hrs, dss.rem_hrs, dss.awake_hrs,
  b.body_age_years, b.age_delta_years;

CREATE UNIQUE INDEX ux_daily_summary_date ON daily_summary(date);
COMMENT ON MATERIALIZED VIEW daily_summary IS 'Materialised daily metrics view, sourcing Apple data from new normalized tables.';


-- -----------------------------------------------------------------------------
-- View: metrics_overview
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW metrics_overview AS
    SELECT
        'weight'::text AS metric_name,
        (SELECT weight_kg FROM daily_summary WHERE date = current_date - 1)::numeric AS yesterday_value,
        (SELECT weight_kg FROM daily_summary WHERE date = current_date - 2)::numeric AS day_before_value,
        (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS avg_7d,
        (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 14 AND date < current_date) AS avg_14d,
        (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS avg_28d,
        CASE
            WHEN (SELECT weight_kg FROM daily_summary WHERE date = current_date - 1) IS NULL
              OR (SELECT weight_kg FROM daily_summary WHERE date = current_date - 2) IS NULL
            THEN NULL
            ELSE (SELECT weight_kg FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT weight_kg FROM daily_summary WHERE date = current_date - 2)
        END::numeric AS abs_change_d1,
        CASE
            WHEN (SELECT weight_kg FROM daily_summary WHERE date = current_date - 2) IS NULL
              OR (SELECT weight_kg FROM daily_summary WHERE date = current_date - 2) = 0
            THEN NULL
            ELSE ((SELECT weight_kg FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT weight_kg FROM daily_summary WHERE date = current_date - 2))
                 / NULLIF((SELECT weight_kg FROM daily_summary WHERE date = current_date - 2), 0) * 100
        END::numeric AS pct_change_d1,
        (
            (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
            - (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
        ) AS abs_change_7d,
        CASE
            WHEN (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) IS NULL
              OR (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) = 0
            THEN NULL
            ELSE (
                (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
                - (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
            ) / NULLIF((SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date), 0) * 100
        END::numeric AS pct_change_7d,
        (SELECT MAX(weight_kg)::numeric FROM daily_summary) AS all_time_high,
        (SELECT MIN(weight_kg)::numeric FROM daily_summary WHERE weight_kg IS NOT NULL) AS all_time_low,
        (SELECT MAX(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months') AS six_month_high,
        (SELECT MIN(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months' AND weight_kg IS NOT NULL) AS six_month_low,
        (SELECT MAX(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months') AS three_month_high,
        (SELECT MIN(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months' AND weight_kg IS NOT NULL) AS three_month_low,
        (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS moving_avg_7d,
        (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS moving_avg_28d,
        (SELECT AVG(weight_kg)::numeric FROM daily_summary WHERE date >= current_date - 90 AND date < current_date) AS moving_avg_90d

UNION ALL
    SELECT
        'body_fat_pct'::text AS metric_name,
        (SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 1)::numeric AS yesterday_value,
        (SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 2)::numeric AS day_before_value,
        (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS avg_7d,
        (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 14 AND date < current_date) AS avg_14d,
        (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS avg_28d,
        CASE
            WHEN (SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 1) IS NULL
              OR (SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 2) IS NULL
            THEN NULL
            ELSE (SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 2)
        END::numeric AS abs_change_d1,
        CASE
            WHEN (SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 2) IS NULL
              OR (SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 2) = 0
            THEN NULL
            ELSE ((SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 2))
                 / NULLIF((SELECT body_fat_pct FROM daily_summary WHERE date = current_date - 2), 0) * 100
        END::numeric AS pct_change_d1,
        (
            (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
            - (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
        ) AS abs_change_7d,
        CASE
            WHEN (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) IS NULL
              OR (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) = 0
            THEN NULL
            ELSE (
                (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
                - (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
            ) / NULLIF((SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date), 0) * 100
        END::numeric AS pct_change_7d,
        (SELECT MAX(body_fat_pct)::numeric FROM daily_summary) AS all_time_high,
        (SELECT MIN(body_fat_pct)::numeric FROM daily_summary WHERE body_fat_pct IS NOT NULL) AS all_time_low,
        (SELECT MAX(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months') AS six_month_high,
        (SELECT MIN(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months' AND body_fat_pct IS NOT NULL) AS six_month_low,
        (SELECT MAX(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months') AS three_month_high,
        (SELECT MIN(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months' AND body_fat_pct IS NOT NULL) AS three_month_low,
        (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS moving_avg_7d,
        (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS moving_avg_28d,
        (SELECT AVG(body_fat_pct)::numeric FROM daily_summary WHERE date >= current_date - 90 AND date < current_date) AS moving_avg_90d

UNION ALL
    SELECT
        'muscle_pct'::text AS metric_name,
        (SELECT muscle_pct FROM daily_summary WHERE date = current_date - 1)::numeric AS yesterday_value,
        (SELECT muscle_pct FROM daily_summary WHERE date = current_date - 2)::numeric AS day_before_value,
        (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS avg_7d,
        (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 14 AND date < current_date) AS avg_14d,
        (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS avg_28d,
        CASE
            WHEN (SELECT muscle_pct FROM daily_summary WHERE date = current_date - 1) IS NULL
              OR (SELECT muscle_pct FROM daily_summary WHERE date = current_date - 2) IS NULL
            THEN NULL
            ELSE (SELECT muscle_pct FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT muscle_pct FROM daily_summary WHERE date = current_date - 2)
        END::numeric AS abs_change_d1,
        CASE
            WHEN (SELECT muscle_pct FROM daily_summary WHERE date = current_date - 2) IS NULL
              OR (SELECT muscle_pct FROM daily_summary WHERE date = current_date - 2) = 0
            THEN NULL
            ELSE ((SELECT muscle_pct FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT muscle_pct FROM daily_summary WHERE date = current_date - 2))
                 / NULLIF((SELECT muscle_pct FROM daily_summary WHERE date = current_date - 2), 0) * 100
        END::numeric AS pct_change_d1,
        (
            (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
            - (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
        ) AS abs_change_7d,
        CASE
            WHEN (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) IS NULL
              OR (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) = 0
            THEN NULL
            ELSE (
                (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
                - (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
            ) / NULLIF((SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date), 0) * 100
        END::numeric AS pct_change_7d,
        (SELECT MAX(muscle_pct)::numeric FROM daily_summary) AS all_time_high,
        (SELECT MIN(muscle_pct)::numeric FROM daily_summary WHERE muscle_pct IS NOT NULL) AS all_time_low,
        (SELECT MAX(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months') AS six_month_high,
        (SELECT MIN(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months' AND muscle_pct IS NOT NULL) AS six_month_low,
        (SELECT MAX(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months') AS three_month_high,
        (SELECT MIN(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months' AND muscle_pct IS NOT NULL) AS three_month_low,
        (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS moving_avg_7d,
        (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS moving_avg_28d,
        (SELECT AVG(muscle_pct)::numeric FROM daily_summary WHERE date >= current_date - 90 AND date < current_date) AS moving_avg_90d

UNION ALL
    SELECT
        'resting_heart_rate'::text AS metric_name,
        (SELECT hr_resting FROM daily_summary WHERE date = current_date - 1)::numeric AS yesterday_value,
        (SELECT hr_resting FROM daily_summary WHERE date = current_date - 2)::numeric AS day_before_value,
        (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS avg_7d,
        (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 14 AND date < current_date) AS avg_14d,
        (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS avg_28d,
        CASE
            WHEN (SELECT hr_resting FROM daily_summary WHERE date = current_date - 1) IS NULL
              OR (SELECT hr_resting FROM daily_summary WHERE date = current_date - 2) IS NULL
            THEN NULL
            ELSE (SELECT hr_resting FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT hr_resting FROM daily_summary WHERE date = current_date - 2)
        END::numeric AS abs_change_d1,
        CASE
            WHEN (SELECT hr_resting FROM daily_summary WHERE date = current_date - 2) IS NULL
              OR (SELECT hr_resting FROM daily_summary WHERE date = current_date - 2) = 0
            THEN NULL
            ELSE ((SELECT hr_resting FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT hr_resting FROM daily_summary WHERE date = current_date - 2))
                 / NULLIF((SELECT hr_resting FROM daily_summary WHERE date = current_date - 2), 0) * 100
        END::numeric AS pct_change_d1,
        (
            (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
            - (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
        ) AS abs_change_7d,
        CASE
            WHEN (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) IS NULL
              OR (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) = 0
            THEN NULL
            ELSE (
                (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
                - (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
            ) / NULLIF((SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date), 0) * 100
        END::numeric AS pct_change_7d,
        (SELECT MAX(hr_resting)::numeric FROM daily_summary) AS all_time_high,
        (SELECT MIN(hr_resting)::numeric FROM daily_summary WHERE hr_resting IS NOT NULL) AS all_time_low,
        (SELECT MAX(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months') AS six_month_high,
        (SELECT MIN(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months' AND hr_resting IS NOT NULL) AS six_month_low,
        (SELECT MAX(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months') AS three_month_high,
        (SELECT MIN(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months' AND hr_resting IS NOT NULL) AS three_month_low,
        (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS moving_avg_7d,
        (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS moving_avg_28d,
        (SELECT AVG(hr_resting)::numeric FROM daily_summary WHERE date >= current_date - 90 AND date < current_date) AS moving_avg_90d

UNION ALL
    SELECT
        'steps'::text AS metric_name,
        (SELECT steps FROM daily_summary WHERE date = current_date - 1)::numeric AS yesterday_value,
        (SELECT steps FROM daily_summary WHERE date = current_date - 2)::numeric AS day_before_value,
        (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS avg_7d,
        (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 14 AND date < current_date) AS avg_14d,
        (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS avg_28d,
        CASE
            WHEN (SELECT steps FROM daily_summary WHERE date = current_date - 1) IS NULL
              OR (SELECT steps FROM daily_summary WHERE date = current_date - 2) IS NULL
            THEN NULL
            ELSE (SELECT steps FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT steps FROM daily_summary WHERE date = current_date - 2)
        END::numeric AS abs_change_d1,
        CASE
            WHEN (SELECT steps FROM daily_summary WHERE date = current_date - 2) IS NULL
              OR (SELECT steps FROM daily_summary WHERE date = current_date - 2) = 0
            THEN NULL
            ELSE ((SELECT steps FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT steps FROM daily_summary WHERE date = current_date - 2))
                 / NULLIF((SELECT steps FROM daily_summary WHERE date = current_date - 2), 0) * 100
        END::numeric AS pct_change_d1,
        (
            (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
            - (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
        ) AS abs_change_7d,
        CASE
            WHEN (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) IS NULL
              OR (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) = 0
            THEN NULL
            ELSE (
                (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
                - (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
            ) / NULLIF((SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date), 0) * 100
        END::numeric AS pct_change_7d,
        (SELECT MAX(steps)::numeric FROM daily_summary) AS all_time_high,
        (SELECT MIN(steps)::numeric FROM daily_summary WHERE steps IS NOT NULL) AS all_time_low,
        (SELECT MAX(steps)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months') AS six_month_high,
        (SELECT MIN(steps)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months' AND steps IS NOT NULL) AS six_month_low,
        (SELECT MAX(steps)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months') AS three_month_high,
        (SELECT MIN(steps)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months' AND steps IS NOT NULL) AS three_month_low,
        (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS moving_avg_7d,
        (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS moving_avg_28d,
        (SELECT AVG(steps)::numeric FROM daily_summary WHERE date >= current_date - 90 AND date < current_date) AS moving_avg_90d

UNION ALL
    SELECT
        'strength_volume'::text AS metric_name,
        (SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 1)::numeric AS yesterday_value,
        (SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 2)::numeric AS day_before_value,
        (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS avg_7d,
        (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 14 AND date < current_date) AS avg_14d,
        (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS avg_28d,
        CASE
            WHEN (SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 1) IS NULL
              OR (SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 2) IS NULL
            THEN NULL
            ELSE (SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 2)
        END::numeric AS abs_change_d1,
        CASE
            WHEN (SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 2) IS NULL
              OR (SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 2) = 0
            THEN NULL
            ELSE ((SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 1)
                 - (SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 2))
                 / NULLIF((SELECT strength_volume_kg FROM daily_summary WHERE date = current_date - 2), 0) * 100
        END::numeric AS pct_change_d1,
        (
            (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
            - (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
        ) AS abs_change_7d,
        CASE
            WHEN (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) IS NULL
              OR (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) = 0
            THEN NULL
            ELSE (
                (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
                - (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
            ) / NULLIF((SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date), 0) * 100
        END::numeric AS pct_change_7d,
        (SELECT MAX(strength_volume_kg)::numeric FROM daily_summary) AS all_time_high,
        (SELECT MIN(strength_volume_kg)::numeric FROM daily_summary WHERE strength_volume_kg IS NOT NULL) AS all_time_low,
        (SELECT MAX(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months') AS six_month_high,
        (SELECT MIN(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '6 months' AND strength_volume_kg IS NOT NULL) AS six_month_low,
        (SELECT MAX(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months') AS three_month_high,
        (SELECT MIN(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - INTERVAL '3 months' AND strength_volume_kg IS NOT NULL) AS three_month_low,
        (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date) AS moving_avg_7d,
        (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) AS moving_avg_28d,
        (SELECT AVG(strength_volume_kg)::numeric FROM daily_summary WHERE date >= current_date - 90 AND date < current_date) AS moving_avg_90d

UNION ALL
SELECT
    'sleep_hours'::text AS metric_name,
    (SELECT sleep_total_minutes / 60.0 FROM daily_summary WHERE date = current_date - 1)::numeric,
    (SELECT sleep_total_minutes / 60.0 FROM daily_summary WHERE date = current_date - 2)::numeric,
    (SELECT AVG(sleep_total_minutes) / 60.0 FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)::numeric,
    (SELECT AVG(sleep_total_minutes) / 60.0 FROM daily_summary WHERE date >= current_date - 14 AND date < current_date)::numeric,
    (SELECT AVG(sleep_total_minutes) / 60.0 FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)::numeric,
    CASE
        WHEN (SELECT sleep_total_minutes FROM daily_summary WHERE date = current_date - 2) IS NULL
        THEN NULL
        ELSE ((SELECT sleep_total_minutes FROM daily_summary WHERE date = current_date - 1)
              - (SELECT sleep_total_minutes FROM daily_summary WHERE date = current_date - 2)) / 60.0
    END::numeric AS abs_change_d1,
    CASE
        WHEN (SELECT sleep_total_minutes FROM daily_summary WHERE date = current_date - 2) IS NULL
          OR (SELECT sleep_total_minutes FROM daily_summary WHERE date = current_date - 2) = 0
        THEN NULL
        ELSE ((SELECT sleep_total_minutes FROM daily_summary WHERE date = current_date - 1)
              - (SELECT sleep_total_minutes FROM daily_summary WHERE date = current_date - 2))
              / NULLIF((SELECT sleep_total_minutes FROM daily_summary WHERE date = current_date - 2), 0) * 100
    END::numeric AS pct_change_d1,
    ((SELECT AVG(sleep_total_minutes)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
      - (SELECT AVG(sleep_total_minutes)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)) / 60.0 AS abs_change_7d,
    CASE
        WHEN (SELECT AVG(sleep_total_minutes)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) IS NULL
          OR (SELECT AVG(sleep_total_minutes)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date) = 0
        THEN NULL
        ELSE (
            (SELECT AVG(sleep_total_minutes)::numeric FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)
            - (SELECT AVG(sleep_total_minutes)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)
        ) / NULLIF((SELECT AVG(sleep_total_minutes)::numeric FROM daily_summary WHERE date >= current_date - 28 AND date < current_date), 0) * 100
    END::numeric AS pct_change_7d,
    (SELECT MAX(sleep_total_minutes) / 60.0 FROM daily_summary),
    (SELECT MIN(sleep_total_minutes) / 60.0 FROM daily_summary WHERE sleep_total_minutes IS NOT NULL),
    (SELECT MAX(sleep_total_minutes) / 60.0 FROM daily_summary WHERE date >= current_date - INTERVAL '6 months'),
    (SELECT MIN(sleep_total_minutes) / 60.0 FROM daily_summary WHERE date >= current_date - INTERVAL '6 months' AND sleep_total_minutes IS NOT NULL),
    (SELECT MAX(sleep_total_minutes) / 60.0 FROM daily_summary WHERE date >= current_date - INTERVAL '3 months'),
    (SELECT MIN(sleep_total_minutes) / 60.0 FROM daily_summary WHERE date >= current_date - INTERVAL '3 months' AND sleep_total_minutes IS NOT NULL),
    (SELECT AVG(sleep_total_minutes) / 60.0 FROM daily_summary WHERE date >= current_date - 7 AND date < current_date)::numeric AS moving_avg_7d,
    (SELECT AVG(sleep_total_minutes) / 60.0 FROM daily_summary WHERE date >= current_date - 28 AND date < current_date)::numeric AS moving_avg_28d,
    (SELECT AVG(sleep_total_minutes) / 60.0 FROM daily_summary WHERE date >= current_date - 90 AND date < current_date)::numeric AS moving_avg_90d

UNION ALL
SELECT
    'squat_volume'::text AS metric_name,
    (
        SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
        FROM wger_logs w
        JOIN wger_exercise e ON e.id = w.exercise_id
        WHERE w.date = current_date - 1 AND LOWER(e.name) LIKE '%squat%'
    )::numeric AS yesterday_value,
    (
        SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
        FROM wger_logs w
        JOIN wger_exercise e ON e.id = w.exercise_id
        WHERE w.date = current_date - 2 AND LOWER(e.name) LIKE '%squat%'
    )::numeric AS day_before_value,
    (
        SELECT AVG(volume)::numeric
        FROM (
            SELECT g::date AS dt, COALESCE(
                (SELECT SUM(w.weight_kg * w.reps)
                 FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                 WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                0
            ) AS volume
            FROM generate_series(current_date - 7, current_date - 1, interval '1 day') AS s(g)
        ) sub
    ) AS avg_7d,
    (
        SELECT AVG(volume)::numeric
        FROM (
            SELECT g::date AS dt, COALESCE(
                (SELECT SUM(w.weight_kg * w.reps)
                 FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                 WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                0
            ) AS volume
            FROM generate_series(current_date - 14, current_date - 1, interval '1 day') AS s(g)
        ) sub
    ) AS avg_14d,
    (
        SELECT AVG(volume)::numeric
        FROM (
            SELECT g::date AS dt, COALESCE(
                (SELECT SUM(w.weight_kg * w.reps)
                 FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                 WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                0
            ) AS volume
            FROM generate_series(current_date - 28, current_date - 1, interval '1 day') AS s(g)
        ) sub
    ) AS avg_28d,
    (
        SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
        FROM wger_logs w
        JOIN wger_exercise e ON e.id = w.exercise_id
        WHERE w.date = current_date - 1 AND LOWER(e.name) LIKE '%squat%'
    )
    - (
        SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
        FROM wger_logs w
        JOIN wger_exercise e ON e.id = w.exercise_id
        WHERE w.date = current_date - 2 AND LOWER(e.name) LIKE '%squat%'
    ) AS abs_change_d1,
    CASE
        WHEN (
            SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
            FROM wger_logs w
            JOIN wger_exercise e ON e.id = w.exercise_id
            WHERE w.date = current_date - 2 AND LOWER(e.name) LIKE '%squat%'
        ) = 0
        THEN NULL
        ELSE (
            (
                SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
                FROM wger_logs w
                JOIN wger_exercise e ON e.id = w.exercise_id
                WHERE w.date = current_date - 1 AND LOWER(e.name) LIKE '%squat%'
            )
            - (
                SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
                FROM wger_logs w
                JOIN wger_exercise e ON e.id = w.exercise_id
                WHERE w.date = current_date - 2 AND LOWER(e.name) LIKE '%squat%'
            )
        ) / NULLIF((
            SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
            FROM wger_logs w
            JOIN wger_exercise e ON e.id = w.exercise_id
            WHERE w.date = current_date - 2 AND LOWER(e.name) LIKE '%squat%'
        ), 0) * 100
    END::numeric AS pct_change_d1,
    (
        SELECT AVG(volume)::numeric
        FROM (
            SELECT g::date AS dt, COALESCE(
                (SELECT SUM(w.weight_kg * w.reps)
                 FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                 WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                0
            ) AS volume
            FROM generate_series(current_date - 7, current_date - 1, interval '1 day') AS s(g)
        ) sub
    )
    - (
        SELECT AVG(volume)::numeric
        FROM (
            SELECT g::date AS dt, COALESCE(
                (SELECT SUM(w.weight_kg * w.reps)
                 FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                 WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                0
            ) AS volume
            FROM generate_series(current_date - 28, current_date - 1, interval '1 day') AS s(g)
        ) sub
    ) AS abs_change_7d,
    CASE
        WHEN (
            SELECT AVG(volume)::numeric
            FROM (
                SELECT g::date AS dt, COALESCE(
                    (SELECT SUM(w.weight_kg * w.reps)
                     FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                     WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                    0
                ) AS volume
                FROM generate_series(current_date - 28, current_date - 1, interval '1 day') AS s(g)
            ) sub
        ) = 0
        THEN NULL
        ELSE (
            (
                SELECT AVG(volume)::numeric
                FROM (
                    SELECT g::date AS dt, COALESCE(
                        (SELECT SUM(w.weight_kg * w.reps)
                         FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                         WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                        0
                    ) AS volume
                    FROM generate_series(current_date - 7, current_date - 1, interval '1 day') AS s(g)
                ) sub
            )
            - (
                SELECT AVG(volume)::numeric
                FROM (
                    SELECT g::date AS dt, COALESCE(
                        (SELECT SUM(w.weight_kg * w.reps)
                         FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                         WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                        0
                    ) AS volume
                    FROM generate_series(current_date - 28, current_date - 1, interval '1 day') AS s(g)
                ) sub
            )
        ) / NULLIF((
            SELECT AVG(volume)::numeric
            FROM (
                SELECT g::date AS dt, COALESCE(
                    (SELECT SUM(w.weight_kg * w.reps)
                     FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                     WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                    0
                ) AS volume
                FROM generate_series(current_date - 28, current_date - 1, interval '1 day') AS s(g)
            ) sub
        ), 0) * 100
    END::numeric AS pct_change_7d,
    (
        SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
        FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
        WHERE LOWER(e.name) LIKE '%squat%'
        GROUP BY w.date
        ORDER BY SUM(w.weight_kg * w.reps) DESC
        LIMIT 1
    )::numeric AS all_time_high,
    (
        SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
        FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
        WHERE LOWER(e.name) LIKE '%squat%'
        GROUP BY w.date
        ORDER BY SUM(w.weight_kg * w.reps) ASC
        LIMIT 1
    )::numeric AS all_time_low,
    (
        SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
        FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
        WHERE LOWER(e.name) LIKE '%squat%' AND w.date >= current_date - INTERVAL '6 months'
        GROUP BY w.date
        ORDER BY SUM(w.weight_kg * w.reps) DESC
        LIMIT 1
    )::numeric AS six_month_high,
    (
        SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
        FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
        WHERE LOWER(e.name) LIKE '%squat%' AND w.date >= current_date - INTERVAL '6 months'
        GROUP BY w.date
        ORDER BY SUM(w.weight_kg * w.reps) ASC
        LIMIT 1
    )::numeric AS six_month_low,
    (
        SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
        FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
        WHERE LOWER(e.name) LIKE '%squat%' AND w.date >= current_date - INTERVAL '3 months'
        GROUP BY w.date
        ORDER BY SUM(w.weight_kg * w.reps) DESC
        LIMIT 1
    )::numeric AS three_month_high,
    (
        SELECT COALESCE(SUM(w.weight_kg * w.reps), 0)
        FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
        WHERE LOWER(e.name) LIKE '%squat%' AND w.date >= current_date - INTERVAL '3 months'
        GROUP BY w.date
        ORDER BY SUM(w.weight_kg * w.reps) ASC
        LIMIT 1
    )::numeric AS three_month_low,
    (
        SELECT AVG(volume)::numeric
        FROM (
            SELECT g::date AS dt, COALESCE(
                (SELECT SUM(w.weight_kg * w.reps)
                 FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                 WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                0
            ) AS volume
            FROM generate_series(current_date - 7, current_date - 1, interval '1 day') AS s(g)
        ) sub
    ) AS moving_avg_7d,
    (
        SELECT AVG(volume)::numeric
        FROM (
            SELECT g::date AS dt, COALESCE(
                (SELECT SUM(w.weight_kg * w.reps)
                 FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                 WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                0
            ) AS volume
            FROM generate_series(current_date - 28, current_date - 1, interval '1 day') AS s(g)
        ) sub
    ) AS moving_avg_28d,
    (
        SELECT AVG(volume)::numeric
        FROM (
            SELECT g::date AS dt, COALESCE(
                (SELECT SUM(w.weight_kg * w.reps)
                 FROM wger_logs w JOIN wger_exercise e ON e.id = w.exercise_id
                 WHERE w.date = g::date AND LOWER(e.name) LIKE '%squat%'),
                0
            ) AS volume
            FROM generate_series(current_date - 90, current_date - 1, interval '1 day') AS s(g)
        ) sub
    ) AS moving_avg_90d
;
COMMENT ON VIEW metrics_overview IS 'Aggregated metric snapshot for Pierre''s trainer narrative.';

-- -----------------------------------------------------------------------------
-- Other MVs (No changes in this version)
-- -----------------------------------------------------------------------------
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
JOIN training_plan_weeks tw ON tpw.week_id = tw.id
JOIN training_plans tp ON tw.plan_id = tp.id
JOIN wger_exercise e ON tpw.exercise_id = e.id
LEFT JOIN wger_exercise_muscle_primary p ON e.id = p.exercise_id
LEFT JOIN wger_exercise_muscle_secondary s ON e.id = s.exercise_id
LEFT JOIN wger_muscle m ON m.id = COALESCE(p.muscle_id, s.muscle_id)
GROUP BY tp.id, tw.week_number, m.id;

CREATE UNIQUE INDEX ux_plan_muscle_volume ON plan_muscle_volume (plan_id, week_number, muscle_id);

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

CREATE UNIQUE INDEX ux_actual_muscle_volume ON actual_muscle_volume (date, muscle_id);


-- =============================================================================
-- SECTION 3: STORED PROCEDURES
-- (No changes needed; depends on daily_summary view which maintains its interface)
-- =============================================================================
CREATE OR REPLACE FUNCTION sp_upsert_body_age(p_target_date date, p_birth_date date)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_start               date := p_target_date - INTERVAL '6 days';
    v_bodyfat_avg         double precision;
    v_steps_avg           double precision;
    v_ex_min_avg          double precision;
    v_rhr_avg             double precision;
    v_sleep_asleep_avg    double precision;
    v_vo2                 double precision;
    v_crf                 double precision;
    v_body_comp           double precision;
    v_steps_score         double precision;
    v_ex_score            double precision;
    v_activity            double precision;
    v_sleep_score         double precision;
    v_rhr_score           double precision;
    v_recovery            double precision;
    v_composite           double precision;
    v_chrono_years        double precision;
    v_body_age            double precision;
    v_cap_min             double precision;
    v_cap_applied         boolean;
    v_any_rows            integer;
BEGIN
    IF p_target_date IS NULL OR p_birth_date IS NULL THEN
        RAISE EXCEPTION 'sp_upsert_body_age: Both p_target_date and p_birth_date are required';
    END IF;
    SELECT COUNT(*) INTO v_any_rows FROM daily_summary ds WHERE ds.date BETWEEN v_start AND p_target_date;
    IF v_any_rows = 0 THEN RETURN; END IF;
    SELECT avg(ds.body_fat_pct)::double precision, avg(ds.steps)::double precision, avg(ds.exercise_minutes)::double precision, avg(ds.hr_resting)::double precision, avg(ds.sleep_asleep_minutes)::double precision
    INTO v_bodyfat_avg, v_steps_avg, v_ex_min_avg, v_rhr_avg, v_sleep_asleep_avg FROM daily_summary ds WHERE ds.date BETWEEN v_start AND p_target_date;
    v_chrono_years := EXTRACT(EPOCH FROM (p_target_date::timestamp - p_birth_date::timestamp)) / 31557600.0;
    -- TODO: consider projecting Apple Health's direct VO₂ max metric
    -- (MetricType.name = 'vo2_max') into ``daily_summary`` and, when available,
    -- bypassing the proxy formula below.  ``used_vo2max_direct`` tracks whether
    -- such a value was applied.
    IF v_rhr_avg IS NOT NULL THEN v_vo2 := 38 - 0.15 * (v_chrono_years - 40) - 0.15 * (COALESCE(v_rhr_avg, 60) - 60) + 0.01 * COALESCE(v_ex_min_avg, 0);
    ELSE v_vo2 := 35; END IF;
    v_crf := GREATEST(0.0, LEAST(100.0, ((v_vo2 - 20.0) / 40.0) * 100.0));
    IF v_bodyfat_avg IS NULL THEN v_body_comp := 50.0; ELSIF v_bodyfat_avg <= 15.0 THEN v_body_comp := 100.0; ELSIF v_bodyfat_avg >= 30.0 THEN v_body_comp := 0.0;
    ELSE v_body_comp := (30.0 - v_bodyfat_avg) / 15.0 * 100.0; END IF;
    v_steps_score := CASE WHEN v_steps_avg IS NULL THEN 0.0 ELSE GREATEST(0.0, LEAST(100.0, (v_steps_avg / 12000.0) * 100.0)) END;
    v_ex_score := CASE WHEN v_ex_min_avg IS NULL THEN 0.0 ELSE GREATEST(0.0, LEAST(100.0, (v_ex_min_avg / 30.0) * 100.0)) END;
    v_activity := 0.6 * v_steps_score + 0.4 * v_ex_score;
    v_sleep_score := CASE WHEN v_sleep_asleep_avg IS NULL THEN 50.0 ELSE GREATEST(0.0, LEAST(100.0, 100.0 - (ABS(v_sleep_asleep_avg - 450.0) / 150.0) * 60.0)) END;
    v_rhr_score := CASE WHEN v_rhr_avg IS NULL THEN 50.0 WHEN v_rhr_avg <= 55.0 THEN 90.0 WHEN v_rhr_avg <= 60.0 THEN 80.0 WHEN v_rhr_avg <= 70.0 THEN 60.0 WHEN v_rhr_avg <= 80.0 THEN 40.0 ELSE 20.0 END;
    -- TODO: Heart Rate Variability (HRV) could adjust ``v_rhr_score`` once the
    -- metric is sourced from Apple Health.  E.g. scale the recovery score down
    -- if the nightly HRV trend indicates fatigue.
    v_recovery := 0.66 * v_sleep_score + 0.34 * v_rhr_score;
    v_composite := 0.40 * v_crf + 0.25 * v_body_comp + 0.20 * v_activity + 0.15 * v_recovery;
    v_body_age := v_chrono_years - 0.2 * (v_composite - 50.0);
    v_cap_min := v_chrono_years - 10.0;
    IF v_body_age < v_cap_min THEN v_body_age := v_cap_min; v_cap_applied := true; ELSE v_cap_applied := false; END IF;
    INSERT INTO body_age_daily (date, input_window_days, crf_score, body_comp_score, activity_score, recovery_score, composite_score, body_age_years, age_delta_years, used_vo2max_direct, cap_minus_10_applied, updated_at)
    VALUES (p_target_date, 7, ROUND(v_crf::numeric, 1), ROUND(v_body_comp::numeric, 1), ROUND(v_activity::numeric, 1), ROUND(v_recovery::numeric, 1), ROUND(v_composite::numeric, 1), ROUND(v_body_age::numeric, 1), ROUND((v_body_age - v_chrono_years)::numeric, 1), false, v_cap_applied, now())
    ON CONFLICT (date) DO UPDATE SET
        input_window_days = EXCLUDED.input_window_days, crf_score = EXCLUDED.crf_score, body_comp_score = EXCLUDED.body_comp_score, activity_score = EXCLUDED.activity_score, recovery_score = EXCLUDED.recovery_score, composite_score = EXCLUDED.composite_score,
        body_age_years = EXCLUDED.body_age_years, age_delta_years = EXCLUDED.age_delta_years, used_vo2max_direct = EXCLUDED.used_vo2max_direct, cap_minus_10_applied = EXCLUDED.cap_minus_10_applied, updated_at = now();
END;
$$;

CREATE OR REPLACE FUNCTION sp_upsert_body_age_range(p_start_date date, p_end_date date, p_birth_date date)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE d date;
BEGIN
    IF p_start_date IS NULL OR p_end_date IS NULL OR p_start_date > p_end_date THEN
        RAISE EXCEPTION 'sp_upsert_body_age_range: invalid date range %, %', p_start_date, p_end_date;
    END IF;
    d := p_start_date;
    WHILE d <= p_end_date LOOP
        PERFORM sp_upsert_body_age(d, p_birth_date);
        d := d + INTERVAL '1 day';
    END LOOP;
END;
$$;


-- =============================================================================
-- SECTION 4: APPLICATION LOGGING & METADATA
-- =============================================================================
CREATE TABLE "ImportLog" (
    import_id SERIAL PRIMARY KEY,
    import_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_file_processed_at TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE "ImportLog" IS 'Tracks the progress of the Dropbox import process to avoid re-importing files.';
COMMENT ON COLUMN "ImportLog".import_id IS 'A unique identifier for each import run.';
COMMENT ON COLUMN "ImportLog".import_timestamp IS 'The timestamp when the import script was executed.';
COMMENT ON COLUMN "ImportLog".last_file_processed_at IS 'The ''client_modified'' timestamp of the last file processed in this run.';


-- =============================================================================
-- SECTION 5: PERMISSIONS
-- =============================================================================
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO pete_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO pete_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO pete_user;