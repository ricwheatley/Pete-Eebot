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
--  - Introduced the 'daily_summary' table to aggregate data from
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
DROP TABLE IF EXISTS training_cycle CASCADE;
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
DROP TABLE IF EXISTS daily_summary CASCADE;
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

CREATE TABLE training_cycle (
    id SERIAL PRIMARY KEY,
    start_date DATE NOT NULL,
    current_week INT NOT NULL,
    current_block INT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE training_cycle IS 'Tracks the state of the 13-week 5/3/1 macrocycle.';

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

CREATE TABLE daily_summary (
  date                 DATE PRIMARY KEY,
  weight_kg            NUMERIC(5,2),
  body_fat_pct         NUMERIC(4,2),
  muscle_pct           NUMERIC(4,2),
  water_pct            NUMERIC(4,2),

  -- Activity / energy
  steps                DOUBLE PRECISION,
  exercise_minutes     DOUBLE PRECISION,
  calories_active      DOUBLE PRECISION,
  calories_resting     DOUBLE PRECISION,
  stand_minutes        DOUBLE PRECISION,
  distance_m           DOUBLE PRECISION,

  -- New Apple metrics
  flights_climbed            DOUBLE PRECISION,
  respiratory_rate           DOUBLE PRECISION,
  walking_hr_avg             DOUBLE PRECISION,
  blood_oxygen_saturation    DOUBLE PRECISION,
  wrist_temperature          DOUBLE PRECISION,
  time_in_daylight           DOUBLE PRECISION,
  cardio_recovery            DOUBLE PRECISION,

  -- Heart and fitness
  hr_resting           DOUBLE PRECISION,
  hrv_sdnn_ms          DOUBLE PRECISION,
  vo2_max              DOUBLE PRECISION,
  hr_avg               DOUBLE PRECISION,
  hr_max               SMALLINT,
  hr_min               SMALLINT,

  -- Sleep
  sleep_total_minutes  NUMERIC,
  sleep_asleep_minutes NUMERIC,
  sleep_rem_minutes    NUMERIC,
  sleep_deep_minutes   NUMERIC,
  sleep_core_minutes   NUMERIC,
  sleep_awake_minutes  NUMERIC,

  -- Body age and strength
  body_age_years       NUMERIC(6,1),
  body_age_delta_years NUMERIC(6,1),
  strength_volume_kg   NUMERIC
);

COMMENT ON TABLE daily_summary IS
'Daily metrics summary table. Refreshed by sp_refresh_daily_summary(). '
'Includes flights climbed, respiratory and walking HR metrics, blood oxygen, sleep wrist temperature, daylight exposure and cardio recovery for richer wellness monitoring.';


-- =============================================================================
-- SECTION 2: FUNCTIONS AND PROCEDURES
-- =============================================================================

CREATE OR REPLACE FUNCTION sp_refresh_daily_summary(p_start DATE, p_end DATE)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  -- Temporary staging table mirroring daily_summary, with added metrics
  CREATE TEMP TABLE tmp_daily_summary (
    date DATE PRIMARY KEY,
    weight_kg NUMERIC(5,2),
    body_fat_pct NUMERIC(4,2),
    muscle_pct NUMERIC(4,2),
    water_pct NUMERIC(4,2),
    steps DOUBLE PRECISION,
    exercise_minutes DOUBLE PRECISION,
    calories_active DOUBLE PRECISION,
    calories_resting DOUBLE PRECISION,
    stand_minutes DOUBLE PRECISION,
    distance_m DOUBLE PRECISION,
    -- new metrics
    flights_climbed DOUBLE PRECISION,
    respiratory_rate DOUBLE PRECISION,
    walking_hr_avg DOUBLE PRECISION,
    blood_oxygen_saturation DOUBLE PRECISION,
    wrist_temperature DOUBLE PRECISION,
    time_in_daylight DOUBLE PRECISION,
    cardio_recovery DOUBLE PRECISION,
    -- existing heart and fitness metrics
    hr_resting DOUBLE PRECISION,
    hrv_sdnn_ms DOUBLE PRECISION,
    vo2_max DOUBLE PRECISION,
    hr_avg DOUBLE PRECISION,
    hr_max SMALLINT,
    hr_min SMALLINT,
    -- sleep metrics
    sleep_total_minutes NUMERIC,
    sleep_asleep_minutes NUMERIC,
    sleep_rem_minutes NUMERIC,
    sleep_deep_minutes NUMERIC,
    sleep_core_minutes NUMERIC,
    sleep_awake_minutes NUMERIC,
    -- body age and strength
    body_age_years NUMERIC(6,1),
    body_age_delta_years NUMERIC(6,1),
    strength_volume_kg NUMERIC
  ) ON COMMIT DROP;

  INSERT INTO tmp_daily_summary(date)
  SELECT generate_series(p_start, p_end, interval '1 day')::date;

  -- Withings body composition
  UPDATE tmp_daily_summary AS tmp
    SET weight_kg = w.weight_kg,
        body_fat_pct = w.body_fat_pct,
        muscle_pct = w.muscle_pct,
        water_pct = w.water_pct
  FROM withings_daily AS w
  WHERE w.date = tmp.date
    AND w.date BETWEEN p_start AND p_end;

  -- Aggregate Apple Health metrics, including the new ones
WITH apple_metrics AS (
    SELECT (dm.date AT TIME ZONE 'Europe/London')::date AS record_date,
           SUM(dm.value) FILTER (WHERE mt.name = 'step_count') AS steps,
           SUM(dm.value) FILTER (WHERE mt.name = 'apple_exercise_time') AS exercise_minutes,
           SUM(dm.value) FILTER (WHERE mt.name = 'active_energy') * 0.239006 AS calories_active,
           SUM(dm.value) FILTER (WHERE mt.name = 'basal_energy_burned') * 0.239006 AS calories_resting,
           SUM(dm.value) FILTER (WHERE mt.name = 'apple_stand_time') AS stand_minutes,
           SUM(dm.value) FILTER (WHERE mt.name = 'distance_walking_running') * 1000 AS distance_m,
           SUM(dm.value) FILTER (WHERE mt.name = 'flights_climbed') AS flights_climbed,
           AVG(dm.value) FILTER (WHERE mt.name = 'respiratory_rate') AS respiratory_rate,
           AVG(dm.value) FILTER (WHERE mt.name = 'walking_heart_rate_average') AS walking_hr_avg,
           AVG(dm.value) FILTER (WHERE mt.name = 'blood_oxygen_saturation') AS blood_oxygen_saturation,
           AVG(dm.value) FILTER (WHERE mt.name = 'apple_sleeping_wrist_temperature') AS wrist_temperature,
           SUM(dm.value) FILTER (WHERE mt.name = 'time_in_daylight') AS time_in_daylight,
           AVG(dm.value) FILTER (WHERE mt.name = 'cardio_recovery') AS cardio_recovery,
           AVG(dm.value) FILTER (WHERE mt.name = 'resting_heart_rate') AS resting_hr,
           AVG(dm.value) FILTER (WHERE mt.name = 'hrv_sdnn_ms') AS hrv_sdnn_ms,
           AVG(dm.value) FILTER (WHERE mt.name = 'vo2_max') AS vo2_max
    FROM "DailyMetric" AS dm
    JOIN "MetricType" AS mt ON dm.metric_id = mt.metric_id
    WHERE dm.date BETWEEN p_start AND (p_end + interval '1 day')
    GROUP BY record_date
)
UPDATE tmp_daily_summary AS tmp
   SET steps                   = am.steps,
       exercise_minutes         = am.exercise_minutes,
       calories_active          = am.calories_active,
       calories_resting         = am.calories_resting,
       stand_minutes            = am.stand_minutes,
       distance_m               = am.distance_m,
       flights_climbed          = am.flights_climbed,
       respiratory_rate         = am.respiratory_rate,
       walking_hr_avg           = am.walking_hr_avg,
       blood_oxygen_saturation  = am.blood_oxygen_saturation,
       wrist_temperature        = am.wrist_temperature,
       time_in_daylight         = am.time_in_daylight,
       cardio_recovery          = am.cardio_recovery,
       hr_resting               = am.resting_hr,
       hrv_sdnn_ms              = am.hrv_sdnn_ms,
       vo2_max                  = am.vo2_max
FROM apple_metrics AS am
WHERE am.record_date = tmp.date;


  -- DailyHeartRateSummary for HR min/avg/max (resting HR now taken from Apple metrics)
  WITH hr_summ AS (
    SELECT date,
           MIN(hr_min) AS hr_min,
           AVG(hr_avg) AS hr_avg,
           MAX(hr_max) AS hr_max
    FROM "DailyHeartRateSummary"
    WHERE date BETWEEN p_start AND p_end
    GROUP BY date
  )
  UPDATE tmp_daily_summary AS tmp
     SET hr_avg = hs.hr_avg,
         hr_max = hs.hr_max,
         hr_min = hs.hr_min
  FROM hr_summ AS hs
  WHERE hs.date = tmp.date;

  -- Sleep durations
  WITH sleep AS (
    SELECT DISTINCT ON (date) date,
           total_sleep_hrs,
           core_hrs,
           deep_hrs,
           rem_hrs,
           awake_hrs
    FROM "DailySleepSummary"
    WHERE date BETWEEN p_start AND p_end
    ORDER BY date, total_sleep_hrs DESC
  )
  UPDATE tmp_daily_summary AS tmp
     SET sleep_total_minutes    = (sleep.total_sleep_hrs * 60)::NUMERIC,
         sleep_asleep_minutes   = ((sleep.core_hrs + sleep.deep_hrs + sleep.rem_hrs) * 60)::NUMERIC,
         sleep_rem_minutes      = (sleep.rem_hrs * 60)::NUMERIC,
         sleep_deep_minutes     = (sleep.deep_hrs * 60)::NUMERIC,
         sleep_core_minutes     = (sleep.core_hrs * 60)::NUMERIC,
         sleep_awake_minutes    = (sleep.awake_hrs * 60)::NUMERIC
  FROM sleep
  WHERE sleep.date = tmp.date;

  -- Body age metrics
  UPDATE tmp_daily_summary AS tmp
     SET body_age_years        = b.body_age_years,
         body_age_delta_years  = b.age_delta_years
  FROM body_age_daily AS b
  WHERE b.date = tmp.date
    AND b.date BETWEEN p_start AND p_end;

  -- Strength training volume (kg × reps)
  WITH strength AS (
    SELECT date,
           SUM(COALESCE(weight_kg, 0) * COALESCE(reps, 0)) AS total_volume
    FROM wger_logs
    WHERE date BETWEEN p_start AND p_end
    GROUP BY date
  )
  UPDATE tmp_daily_summary AS tmp
     SET strength_volume_kg = COALESCE(strength.total_volume, 0)
  FROM strength
  WHERE strength.date = tmp.date;

  UPDATE tmp_daily_summary
     SET strength_volume_kg = 0
   WHERE strength_volume_kg IS NULL;

  -- Upsert into daily_summary
  INSERT INTO daily_summary AS ds
      SELECT * FROM tmp_daily_summary
  ON CONFLICT (date) DO UPDATE SET
      weight_kg            = EXCLUDED.weight_kg,
      body_fat_pct         = EXCLUDED.body_fat_pct,
      muscle_pct           = EXCLUDED.muscle_pct,
      water_pct            = EXCLUDED.water_pct,
      steps                = EXCLUDED.steps,
      exercise_minutes     = EXCLUDED.exercise_minutes,
      calories_active      = EXCLUDED.calories_active,
      calories_resting     = EXCLUDED.calories_resting,
      stand_minutes        = EXCLUDED.stand_minutes,
      distance_m           = EXCLUDED.distance_m,
      flights_climbed      = EXCLUDED.flights_climbed,
      respiratory_rate     = EXCLUDED.respiratory_rate,
      walking_hr_avg       = EXCLUDED.walking_hr_avg,
      blood_oxygen_saturation = EXCLUDED.blood_oxygen_saturation,
      wrist_temperature    = EXCLUDED.wrist_temperature,
      time_in_daylight     = EXCLUDED.time_in_daylight,
      cardio_recovery      = EXCLUDED.cardio_recovery,
      hr_resting           = EXCLUDED.hr_resting,
      hrv_sdnn_ms          = EXCLUDED.hrv_sdnn_ms,
      vo2_max              = EXCLUDED.vo2_max,
      hr_avg               = EXCLUDED.hr_avg,
      hr_max               = EXCLUDED.hr_max,
      hr_min               = EXCLUDED.hr_min,
      sleep_total_minutes  = EXCLUDED.sleep_total_minutes,
      sleep_asleep_minutes = EXCLUDED.sleep_asleep_minutes,
      sleep_rem_minutes    = EXCLUDED.sleep_rem_minutes,
      sleep_deep_minutes   = EXCLUDED.sleep_deep_minutes,
      sleep_core_minutes   = EXCLUDED.sleep_core_minutes,
      sleep_awake_minutes  = EXCLUDED.sleep_awake_minutes,
      body_age_years       = EXCLUDED.body_age_years,
      body_age_delta_years = EXCLUDED.body_age_delta_years,
      strength_volume_kg   = EXCLUDED.strength_volume_kg;
END;
$$;


CREATE OR REPLACE FUNCTION sp_get_daily_metric_overview(
    p_column_name   TEXT,
    p_display_name  TEXT,
    p_ref_date      DATE
) RETURNS TABLE (
    metric_name        TEXT,
    yesterday_value    NUMERIC,
    day_before_value   NUMERIC,
    avg_7d             NUMERIC,
    avg_14d            NUMERIC,
    avg_28d            NUMERIC,
    abs_change_d1      NUMERIC,
    pct_change_d1      NUMERIC,
    abs_change_7d      NUMERIC,
    pct_change_7d      NUMERIC,
    all_time_high      NUMERIC,
    all_time_low       NUMERIC,
    six_month_high     NUMERIC,
    six_month_low      NUMERIC,
    three_month_high   NUMERIC,
    three_month_low    NUMERIC,
    moving_avg_7d      NUMERIC,
    moving_avg_28d     NUMERIC,
    moving_avg_90d     NUMERIC
) LANGUAGE plpgsql AS $$
DECLARE
    col TEXT := format('%I', p_column_name);
    v_yesterday NUMERIC;
    v_day_before NUMERIC;
    v_avg_7d NUMERIC;
    v_avg_14d NUMERIC;
    v_avg_28d NUMERIC;
    v_avg_90d NUMERIC;
    v_all_high NUMERIC;
    v_all_low NUMERIC;
    v_six_high NUMERIC;
    v_six_low NUMERIC;
    v_three_high NUMERIC;
    v_three_low NUMERIC;
BEGIN
    metric_name := p_display_name;

    -- Values on reference date and the day before
    EXECUTE format('SELECT %s FROM daily_summary WHERE date = $1', col)
       INTO v_yesterday USING p_ref_date;
    EXECUTE format('SELECT %s FROM daily_summary WHERE date = $1', col)
       INTO v_day_before USING (p_ref_date - INTERVAL '1 day')::date;

    -- Moving averages (preceding intervals, not including the reference date)
    EXECUTE format(
        'SELECT AVG(%s)::numeric FROM daily_summary WHERE date >= $1 AND date < $2',
        col
    ) INTO v_avg_7d  USING (p_ref_date - INTERVAL '7 days')::date,  p_ref_date;
    EXECUTE format(
        'SELECT AVG(%s)::numeric FROM daily_summary WHERE date >= $1 AND date < $2',
        col
    ) INTO v_avg_14d USING (p_ref_date - INTERVAL '14 days')::date, p_ref_date;
    EXECUTE format(
        'SELECT AVG(%s)::numeric FROM daily_summary WHERE date >= $1 AND date < $2',
        col
    ) INTO v_avg_28d USING (p_ref_date - INTERVAL '28 days')::date, p_ref_date;
    EXECUTE format(
        'SELECT AVG(%s)::numeric FROM daily_summary WHERE date >= $1 AND date < $2',
        col
    ) INTO v_avg_90d USING (p_ref_date - INTERVAL '90 days')::date, p_ref_date;

    -- All‑time and recent highs/lows, restricted to p_ref_date or earlier
    EXECUTE format(
        'SELECT MAX(%s)::numeric FROM daily_summary WHERE date <= $1',
        col
    ) INTO v_all_high USING p_ref_date;
    EXECUTE format(
        'SELECT MIN(%s)::numeric FROM daily_summary WHERE date <= $1 AND %s IS NOT NULL',
        col, col
    ) INTO v_all_low USING p_ref_date;

    EXECUTE format(
        'SELECT MAX(%s)::numeric FROM daily_summary WHERE date >= $1 AND date <= $2',
        col
    ) INTO v_six_high USING (p_ref_date - INTERVAL '6 months')::date, p_ref_date;
    EXECUTE format(
        'SELECT MIN(%s)::numeric FROM daily_summary WHERE date >= $1 AND date <= $2 AND %s IS NOT NULL',
        col, col
    ) INTO v_six_low USING (p_ref_date - INTERVAL '6 months')::date, p_ref_date;

    EXECUTE format(
        'SELECT MAX(%s)::numeric FROM daily_summary WHERE date >= $1 AND date <= $2',
        col
    ) INTO v_three_high USING (p_ref_date - INTERVAL '3 months')::date, p_ref_date;
    EXECUTE format(
        'SELECT MIN(%s)::numeric FROM daily_summary WHERE date >= $1 AND date <= $2 AND %s IS NOT NULL',
        col, col
    ) INTO v_three_low USING (p_ref_date - INTERVAL '3 months')::date, p_ref_date;

    -- Populate output columns
    yesterday_value  := v_yesterday;
    day_before_value := v_day_before;
    avg_7d           := v_avg_7d;
    avg_14d          := v_avg_14d;
    avg_28d          := v_avg_28d;
    moving_avg_7d    := v_avg_7d;
    moving_avg_28d   := v_avg_28d;
    moving_avg_90d   := v_avg_90d;

    IF v_yesterday IS NULL OR v_day_before IS NULL THEN
        abs_change_d1 := NULL;
        pct_change_d1 := NULL;
    ELSE
        abs_change_d1 := v_yesterday - v_day_before;
        IF v_day_before = 0 THEN
            pct_change_d1 := NULL;
        ELSE
            pct_change_d1 := (abs_change_d1 / v_day_before) * 100;
        END IF;
    END IF;

    abs_change_7d := v_avg_7d - v_avg_28d;
    IF v_avg_28d IS NULL OR v_avg_28d = 0 THEN
        pct_change_7d := NULL;
    ELSE
        pct_change_7d := (abs_change_7d / v_avg_28d) * 100;
    END IF;

    all_time_high   := v_all_high;
    all_time_low    := v_all_low;
    six_month_high  := v_six_high;
    six_month_low   := v_six_low;
    three_month_high:= v_three_high;
    three_month_low := v_three_low;

    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION sp_get_exercise_volume_overview(
    p_exercise_id INT,
    p_ref_date    DATE
) RETURNS TABLE (
    metric_name        TEXT,
    yesterday_value    NUMERIC,
    day_before_value   NUMERIC,
    avg_7d             NUMERIC,
    avg_14d            NUMERIC,
    avg_28d            NUMERIC,
    abs_change_d1      NUMERIC,
    pct_change_d1      NUMERIC,
    abs_change_7d      NUMERIC,
    pct_change_7d      NUMERIC,
    all_time_high      NUMERIC,
    all_time_low       NUMERIC,
    six_month_high     NUMERIC,
    six_month_low      NUMERIC,
    three_month_high   NUMERIC,
    three_month_low    NUMERIC,
    moving_avg_7d      NUMERIC,
    moving_avg_28d     NUMERIC,
    moving_avg_90d     NUMERIC
) LANGUAGE plpgsql AS $$
DECLARE
    ex_name TEXT;
    v_yesterday NUMERIC;
    v_day_before NUMERIC;
    v_avg_7d NUMERIC;
    v_avg_14d NUMERIC;
    v_avg_28d NUMERIC;
    v_avg_90d NUMERIC;
    v_all_high NUMERIC;
    v_all_low NUMERIC;
    v_six_high NUMERIC;
    v_six_low NUMERIC;
    v_three_high NUMERIC;
    v_three_low NUMERIC;
BEGIN
    SELECT LOWER(name) INTO ex_name
      FROM wger_exercise
     WHERE id = p_exercise_id;

    metric_name := coalesce(ex_name || '_volume', 'exercise_' || p_exercise_id || '_volume');

    -- Daily volume up to and including ref date
    SELECT COALESCE(SUM(weight_kg * reps), 0) INTO v_yesterday
      FROM wger_logs
     WHERE exercise_id = p_exercise_id AND date = p_ref_date;

    SELECT COALESCE(SUM(weight_kg * reps), 0) INTO v_day_before
      FROM wger_logs
     WHERE exercise_id = p_exercise_id AND date = p_ref_date - INTERVAL '1 day';

    -- Moving averages for 7/14/28/90 days (preceding p_ref_date)
    SELECT AVG(vol)::numeric INTO v_avg_7d
      FROM (
          SELECT g::date AS dt,
                 COALESCE(
                   (SELECT SUM(weight_kg * reps)
                      FROM wger_logs w
                     WHERE w.exercise_id = p_exercise_id AND w.date = g::date),
                   0
                 ) AS vol
            FROM generate_series(p_ref_date - INTERVAL '7 days', p_ref_date - INTERVAL '1 day', interval '1 day') AS s(g)
      ) t;

    SELECT AVG(vol)::numeric INTO v_avg_14d
      FROM (
          SELECT g::date AS dt,
                 COALESCE(
                   (SELECT SUM(weight_kg * reps)
                      FROM wger_logs w
                     WHERE w.exercise_id = p_exercise_id AND w.date = g::date),
                   0
                 ) AS vol
            FROM generate_series(p_ref_date - INTERVAL '14 days', p_ref_date - INTERVAL '1 day', interval '1 day') AS s(g)
      ) t;

    SELECT AVG(vol)::numeric INTO v_avg_28d
      FROM (
          SELECT g::date AS dt,
                 COALESCE(
                   (SELECT SUM(weight_kg * reps)
                      FROM wger_logs w
                     WHERE w.exercise_id = p_exercise_id AND w.date = g::date),
                   0
                 ) AS vol
            FROM generate_series(p_ref_date - INTERVAL '28 days', p_ref_date - INTERVAL '1 day', interval '1 day') AS s(g)
      ) t;

    SELECT AVG(vol)::numeric INTO v_avg_90d
      FROM (
          SELECT g::date AS dt,
                 COALESCE(
                   (SELECT SUM(weight_kg * reps)
                      FROM wger_logs w
                     WHERE w.exercise_id = p_exercise_id AND w.date = g::date),
                   0
                 ) AS vol
            FROM generate_series(p_ref_date - INTERVAL '90 days', p_ref_date - INTERVAL '1 day', interval '1 day') AS s(g)
      ) t;

    -- Highs and lows up to ref date
    SELECT MAX(sum_vol), MIN(sum_vol)
      INTO v_all_high, v_all_low
      FROM (
          SELECT SUM(weight_kg * reps) AS sum_vol
            FROM wger_logs
           WHERE exercise_id = p_exercise_id AND date <= p_ref_date
           GROUP BY date
      ) t;

    -- 6‑month and 3‑month highs/lows up to ref date
    SELECT
      MAX(sum_vol) FILTER (WHERE dt >= p_ref_date - INTERVAL '6 months'),
      MIN(sum_vol) FILTER (WHERE dt >= p_ref_date - INTERVAL '6 months'),
      MAX(sum_vol) FILTER (WHERE dt >= p_ref_date - INTERVAL '3 months'),
      MIN(sum_vol) FILTER (WHERE dt >= p_ref_date - INTERVAL '3 months')
      INTO v_six_high, v_six_low, v_three_high, v_three_low
      FROM (
          SELECT date AS dt, SUM(weight_kg * reps) AS sum_vol
            FROM wger_logs
           WHERE exercise_id = p_exercise_id AND date <= p_ref_date
           GROUP BY date
      ) t;

    yesterday_value  := v_yesterday;
    day_before_value := v_day_before;
    avg_7d           := v_avg_7d;
    avg_14d          := v_avg_14d;
    avg_28d          := v_avg_28d;
    moving_avg_7d    := v_avg_7d;
    moving_avg_28d   := v_avg_28d;
    moving_avg_90d   := v_avg_90d;

    abs_change_d1 := v_yesterday - v_day_before;
    IF v_day_before = 0 THEN
        pct_change_d1 := NULL;
    ELSE
        pct_change_d1 := (abs_change_d1 / v_day_before) * 100;
    END IF;

    abs_change_7d := v_avg_7d - v_avg_28d;
    IF v_avg_28d IS NULL OR v_avg_28d = 0 THEN
        pct_change_7d := NULL;
    ELSE
        pct_change_7d := (abs_change_7d / v_avg_28d) * 100;
    END IF;

    all_time_high    := v_all_high;
    all_time_low     := v_all_low;
    six_month_high   := v_six_high;
    six_month_low    := v_six_low;
    three_month_high := v_three_high;
    three_month_low  := v_three_low;

    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION sp_metrics_overview(p_ref_date DATE)
RETURNS TABLE (
    metric_name        TEXT,
    yesterday_value    NUMERIC,
    day_before_value   NUMERIC,
    avg_7d             NUMERIC,
    avg_14d            NUMERIC,
    avg_28d            NUMERIC,
    abs_change_d1      NUMERIC,
    pct_change_d1      NUMERIC,
    abs_change_7d      NUMERIC,
    pct_change_7d      NUMERIC,
    all_time_high      NUMERIC,
    all_time_low       NUMERIC,
    six_month_high     NUMERIC,
    six_month_low      NUMERIC,
    three_month_high   NUMERIC,
    three_month_low    NUMERIC,
    moving_avg_7d      NUMERIC,
    moving_avg_28d     NUMERIC,
    moving_avg_90d     NUMERIC
) LANGUAGE sql AS $$
    SELECT *
    FROM (
    SELECT * FROM sp_get_daily_metric_overview('weight_kg',             'weight',                p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('body_fat_pct',         'body_fat_pct',          p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('muscle_pct',           'muscle_pct',            p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('water_pct',            'water_pct',             p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('steps',                'steps',                 p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('exercise_minutes',     'exercise_minutes',      p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('calories_active',      'calories_active',       p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('calories_resting',     'calories_resting',      p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('stand_minutes',        'stand_minutes',         p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('distance_m',           'distance_m',            p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('flights_climbed',      'flights_climbed',       p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('respiratory_rate',     'respiratory_rate',      p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('walking_hr_avg',       'walking_hr_avg',        p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('blood_oxygen_saturation','blood_oxygen_saturation',p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('wrist_temperature',    'wrist_temperature',     p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('time_in_daylight',     'time_in_daylight',      p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('cardio_recovery',      'cardio_recovery',       p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('hr_resting',           'resting_heart_rate',    p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('hrv_sdnn_ms',          'hrv_sdnn_ms',           p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('vo2_max',              'vo2_max',               p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('hr_avg',               'hr_avg',                p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('hr_max',               'hr_max',                p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('hr_min',               'hr_min',                p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('sleep_total_minutes',  'sleep_total_minutes',   p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('sleep_asleep_minutes', 'sleep_asleep_minutes',  p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('sleep_rem_minutes',    'sleep_rem_minutes',     p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('sleep_deep_minutes',   'sleep_deep_minutes',    p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('sleep_core_minutes',   'sleep_core_minutes',    p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('sleep_awake_minutes',  'sleep_awake_minutes',   p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('body_age_years',       'body_age_years',        p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('body_age_delta_years', 'body_age_delta_years',  p_ref_date)
    UNION ALL
    SELECT * FROM sp_get_daily_metric_overview('strength_volume_kg',   'strength_volume',       p_ref_date)
    UNION ALL
    -- Big Four lifts (exercise IDs from schedule_rules.py: squat 615, bench 73, deadlift 184, OHP 566)
    SELECT * FROM sp_get_exercise_volume_overview(615, p_ref_date)  -- squat
    UNION ALL
    SELECT * FROM sp_get_exercise_volume_overview(73,  p_ref_date)  -- bench
    UNION ALL
    SELECT * FROM sp_get_exercise_volume_overview(184, p_ref_date)  -- deadlift
    UNION ALL
    SELECT * FROM sp_get_exercise_volume_overview(566, p_ref_date) -- overhead press
    ) t;
$$;

CREATE OR REPLACE FUNCTION sp_plan_for_day(p_date DATE)
RETURNS TABLE (
    workout_date DATE,
    scheduled_time TIME,
    exercise_name TEXT,
    sets INT,
    reps INT,
    target_weight_kg NUMERIC
) LANGUAGE sql AS $$
    SELECT p_date::date AS workout_date,
           tpw.scheduled_time,
           e.name AS exercise_name,
           tpw.sets,
           tpw.reps,
           tpw.target_weight_kg
    FROM training_plan_workouts tpw
    JOIN training_plan_weeks tw ON tpw.week_id = tw.id
    JOIN training_plans tp ON tw.plan_id = tp.id
    JOIN wger_exercise e ON tpw.exercise_id = e.id
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
    target_weight_kg NUMERIC
) LANGUAGE sql AS $$
    SELECT (p_start_date + (tpw.day_of_week - 1))::date AS workout_date,
           tpw.day_of_week,
           tpw.scheduled_time,
           e.name AS exercise_name,
           tpw.sets,
           tpw.reps,
           tpw.target_weight_kg
    FROM training_plan_workouts tpw
    JOIN training_plan_weeks tw ON tpw.week_id = tw.id
    JOIN training_plans tp ON tw.plan_id = tp.id
    JOIN wger_exercise e ON tpw.exercise_id = e.id
    WHERE tp.is_active = TRUE
      AND tp.start_date <= p_start_date
      AND (tp.start_date + ((tw.week_number + 1) * 7)) > p_start_date
    ORDER BY tpw.day_of_week, tpw.scheduled_time;
$$;


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
-- (No changes needed; depends on daily_summary table which maintains its interface)
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
    v_vo2_direct          double precision;
    v_hrv_avg             double precision;
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
    v_used_vo2_direct     boolean := false;
    v_any_rows            integer;
BEGIN
    IF p_target_date IS NULL OR p_birth_date IS NULL THEN
        RAISE EXCEPTION 'sp_upsert_body_age: Both p_target_date and p_birth_date are required';
    END IF;
    SELECT COUNT(*) INTO v_any_rows FROM daily_summary ds WHERE ds.date BETWEEN v_start AND p_target_date;
    IF v_any_rows = 0 THEN RETURN; END IF;
    SELECT
        avg(ds.body_fat_pct)::double precision,
        avg(ds.steps)::double precision,
        avg(ds.exercise_minutes)::double precision,
        avg(ds.hr_resting)::double precision,
        avg(ds.sleep_asleep_minutes)::double precision,
        avg(ds.vo2_max)::double precision,
        avg(ds.hrv_sdnn_ms)::double precision
    INTO v_bodyfat_avg,
         v_steps_avg,
         v_ex_min_avg,
         v_rhr_avg,
         v_sleep_asleep_avg,
         v_vo2_direct,
         v_hrv_avg
    FROM daily_summary ds
    WHERE ds.date BETWEEN v_start AND p_target_date;
    v_chrono_years := EXTRACT(EPOCH FROM (p_target_date::timestamp - p_birth_date::timestamp)) / 31557600.0;
    -- Prefer direct VO2 max measurements when available; otherwise fall back to derived estimate.
    IF v_vo2_direct IS NOT NULL THEN
        v_vo2 := v_vo2_direct;
        v_used_vo2_direct := true;
    ELSIF v_rhr_avg IS NOT NULL THEN
        v_vo2 := 38 - 0.15 * (v_chrono_years - 40) - 0.15 * (COALESCE(v_rhr_avg, 60) - 60) + 0.01 * COALESCE(v_ex_min_avg, 0);
    ELSE
        v_vo2 := 35;
    END IF;
    v_crf := GREATEST(0.0, LEAST(100.0, ((v_vo2 - 20.0) / 40.0) * 100.0));
    IF v_bodyfat_avg IS NULL THEN v_body_comp := 50.0; ELSIF v_bodyfat_avg <= 15.0 THEN v_body_comp := 100.0; ELSIF v_bodyfat_avg >= 30.0 THEN v_body_comp := 0.0;
    ELSE v_body_comp := (30.0 - v_bodyfat_avg) / 15.0 * 100.0; END IF;
    v_steps_score := CASE WHEN v_steps_avg IS NULL THEN 0.0 ELSE GREATEST(0.0, LEAST(100.0, (v_steps_avg / 12000.0) * 100.0)) END;
    v_ex_score := CASE WHEN v_ex_min_avg IS NULL THEN 0.0 ELSE GREATEST(0.0, LEAST(100.0, (v_ex_min_avg / 30.0) * 100.0)) END;
    v_activity := 0.6 * v_steps_score + 0.4 * v_ex_score;
    v_sleep_score := CASE WHEN v_sleep_asleep_avg IS NULL THEN 50.0 ELSE GREATEST(0.0, LEAST(100.0, 100.0 - (ABS(v_sleep_asleep_avg - 450.0) / 150.0) * 60.0)) END;
    v_rhr_score := CASE WHEN v_rhr_avg IS NULL THEN 50.0 WHEN v_rhr_avg <= 55.0 THEN 90.0 WHEN v_rhr_avg <= 60.0 THEN 80.0 WHEN v_rhr_avg <= 70.0 THEN 60.0 WHEN v_rhr_avg <= 80.0 THEN 40.0 ELSE 20.0 END;
    IF v_hrv_avg IS NOT NULL THEN
        IF v_hrv_avg < 25.0 THEN
            v_rhr_score := v_rhr_score - 20.0;
        ELSIF v_hrv_avg < 35.0 THEN
            v_rhr_score := v_rhr_score - 15.0;
        ELSIF v_hrv_avg < 45.0 THEN
            v_rhr_score := v_rhr_score - 10.0;
        ELSIF v_hrv_avg < 55.0 THEN
            v_rhr_score := v_rhr_score - 5.0;
        END IF;
        v_rhr_score := GREATEST(0.0, LEAST(100.0, v_rhr_score));
    END IF;
    v_recovery := 0.66 * v_sleep_score + 0.34 * v_rhr_score;
    v_composite := 0.40 * v_crf + 0.25 * v_body_comp + 0.20 * v_activity + 0.15 * v_recovery;
    v_body_age := v_chrono_years - 0.2 * (v_composite - 50.0);
    v_cap_min := v_chrono_years - 10.0;
    IF v_body_age < v_cap_min THEN v_body_age := v_cap_min; v_cap_applied := true; ELSE v_cap_applied := false; END IF;
    INSERT INTO body_age_daily (date, input_window_days, crf_score, body_comp_score, activity_score, recovery_score, composite_score, body_age_years, age_delta_years, used_vo2max_direct, cap_minus_10_applied, updated_at)
    VALUES (p_target_date, 7, ROUND(v_crf::numeric, 1), ROUND(v_body_comp::numeric, 1), ROUND(v_activity::numeric, 1), ROUND(v_recovery::numeric, 1), ROUND(v_composite::numeric, 1), ROUND(v_body_age::numeric, 1), ROUND((v_body_age - v_chrono_years)::numeric, 1), v_used_vo2_direct, v_cap_applied, now())
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
