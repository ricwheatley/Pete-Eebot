-- 1. Drop the old materialized view (cascades to metrics_overview if it exists)
DROP MATERIALIZED VIEW IF EXISTS daily_summary CASCADE;

-- 2. Create daily_summary as a real table
CREATE TABLE daily_summary (
  date                 DATE PRIMARY KEY,
  weight_kg            NUMERIC(5,2),
  body_fat_pct         NUMERIC(4,2),
  muscle_pct           NUMERIC(4,2),
  water_pct            NUMERIC(4,2),
  steps                DOUBLE PRECISION,
  exercise_minutes     DOUBLE PRECISION,
  calories_active      DOUBLE PRECISION,
  calories_resting     DOUBLE PRECISION,
  stand_minutes        DOUBLE PRECISION,
  distance_m           DOUBLE PRECISION,
  hr_resting           DOUBLE PRECISION,
  hrv_sdnn_ms          DOUBLE PRECISION,
  vo2_max              DOUBLE PRECISION,
  hr_avg               DOUBLE PRECISION,
  hr_max               SMALLINT,
  hr_min               SMALLINT,
  sleep_total_minutes  NUMERIC,
  sleep_asleep_minutes NUMERIC,
  sleep_rem_minutes    NUMERIC,
  sleep_deep_minutes   NUMERIC,
  sleep_core_minutes   NUMERIC,
  sleep_awake_minutes  NUMERIC,
  body_age_years       NUMERIC(6,1),
  body_age_delta_years NUMERIC(6,1),
  strength_volume_kg   NUMERIC
);

COMMENT ON TABLE daily_summary IS
'Daily metrics summary table (formerly a materialized view). Refreshed by sp_refresh_daily_summary().';

-- 3. Upsert function to (re)populate daily_summary
CREATE OR REPLACE FUNCTION sp_refresh_daily_summary(p_start DATE, p_end DATE)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO daily_summary
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
    dss.total_sleep_hrs * 60,
    (dss.core_hrs + dss.deep_hrs + dss.rem_hrs) * 60,
    dss.rem_hrs * 60,
    dss.deep_hrs * 60,
    dss.core_hrs * 60,
    dss.awake_hrs * 60,
    b.body_age_years,
    b.age_delta_years,
    COALESCE(SUM(gl.weight_kg * gl.reps), 0)
  FROM generate_series(p_start, p_end, interval '1 day') AS d(date)
  LEFT JOIN withings_daily w USING (date)
  LEFT JOIN (
      SELECT dm.date,
             SUM(dm.value) FILTER (WHERE mt.name='step_count') AS steps,
             SUM(dm.value) FILTER (WHERE mt.name='apple_exercise_time') AS exercise_minutes,
             SUM(dm.value) FILTER (WHERE mt.name='active_energy')*0.239006 AS calories_active,
             SUM(dm.value) FILTER (WHERE mt.name='basal_energy_burned')*0.239006 AS calories_resting,
             SUM(dm.value) FILTER (WHERE mt.name='apple_stand_time') AS stand_minutes,
             SUM(dm.value) FILTER (WHERE mt.name='distance_walking_running') AS distance_m,
             AVG(dm.value) FILTER (WHERE mt.name='resting_heart_rate') AS hr_resting,
             AVG(dm.value) FILTER (WHERE mt.name='hrv_sdnn_ms') AS hrv_sdnn_ms,
             AVG(dm.value) FILTER (WHERE mt.name='vo2_max') AS vo2_max
      FROM "DailyMetric" dm
      JOIN "MetricType" mt ON dm.metric_id=mt.metric_id
      GROUP BY dm.date
  ) am USING (date)
  LEFT JOIN (
      SELECT date, MIN(hr_min) AS hr_min, AVG(hr_avg) AS hr_avg, MAX(hr_max) AS hr_max
      FROM "DailyHeartRateSummary" GROUP BY date
  ) dhr USING (date)
  LEFT JOIN (
      SELECT DISTINCT ON (date) date,
             total_sleep_hrs, core_hrs, deep_hrs, rem_hrs, awake_hrs
      FROM "DailySleepSummary"
      ORDER BY date, total_sleep_hrs DESC
  ) dss USING (date)
  LEFT JOIN body_age_daily b USING (date)
  LEFT JOIN wger_logs gl USING (date)
  GROUP BY d.date, w.weight_kg, w.body_fat_pct, w.muscle_pct, w.water_pct,
           am.steps, am.exercise_minutes, am.calories_active, am.calories_resting, am.stand_minutes, am.distance_m,
           am.hr_resting, am.hrv_sdnn_ms, am.vo2_max,
           dhr.hr_avg, dhr.hr_max, dhr.hr_min,
           dss.total_sleep_hrs, dss.core_hrs, dss.deep_hrs, dss.rem_hrs, dss.awake_hrs,
           b.body_age_years, b.age_delta_years
  ON CONFLICT (date) DO UPDATE SET
    weight_kg=EXCLUDED.weight_kg,
    body_fat_pct=EXCLUDED.body_fat_pct,
    muscle_pct=EXCLUDED.muscle_pct,
    water_pct=EXCLUDED.water_pct,
    steps=EXCLUDED.steps,
    exercise_minutes=EXCLUDED.exercise_minutes,
    calories_active=EXCLUDED.calories_active,
    calories_resting=EXCLUDED.calories_resting,
    stand_minutes=EXCLUDED.stand_minutes,
    distance_m=EXCLUDED.distance_m,
    hr_resting=EXCLUDED.hr_resting,
    hrv_sdnn_ms=EXCLUDED.hrv_sdnn_ms,
    vo2_max=EXCLUDED.vo2_max,
    hr_avg=EXCLUDED.hr_avg,
    hr_max=EXCLUDED.hr_max,
    hr_min=EXCLUDED.hr_min,
    sleep_total_minutes=EXCLUDED.sleep_total_minutes,
    sleep_asleep_minutes=EXCLUDED.sleep_asleep_minutes,
    sleep_rem_minutes=EXCLUDED.sleep_rem_minutes,
    sleep_deep_minutes=EXCLUDED.sleep_deep_minutes,
    sleep_core_minutes=EXCLUDED.sleep_core_minutes,
    sleep_awake_minutes=EXCLUDED.sleep_awake_minutes,
    body_age_years=EXCLUDED.body_age_years,
    body_age_delta_years=EXCLUDED.body_age_delta_years,
    strength_volume_kg=EXCLUDED.strength_volume_kg;
END;
$$;

-- 4. Seed the table with historic data
SELECT sp_refresh_daily_summary(
  (SELECT LEAST(
     COALESCE((SELECT MIN(date) FROM withings_daily), current_date),
     COALESCE((SELECT MIN(date) FROM "DailyMetric"), current_date),
     COALESCE((SELECT MIN(date) FROM "DailyHeartRateSummary"), current_date),
     COALESCE((SELECT MIN(date) FROM "DailySleepSummary"), current_date)
   )),
  current_date
);
