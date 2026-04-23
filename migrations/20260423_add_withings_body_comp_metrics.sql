BEGIN;

ALTER TABLE withings_daily
    ADD COLUMN IF NOT EXISTS fat_free_mass_kg NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS fat_mass_kg NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS muscle_mass_kg NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS water_mass_kg NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS bone_mass_kg NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS visceral_fat_index NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS bmr_kcal_day NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS nerve_health_score_feet NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS metabolic_age_years NUMERIC(5,2);

ALTER TABLE daily_summary
    ADD COLUMN IF NOT EXISTS fat_free_mass_kg NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS fat_mass_kg NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS muscle_mass_kg NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS water_mass_kg NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS bone_mass_kg NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS visceral_fat_index NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS bmr_kcal_day NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS nerve_health_score_feet NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS metabolic_age_years NUMERIC(5,2);

CREATE OR REPLACE FUNCTION sp_refresh_daily_summary(p_start DATE, p_end DATE)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  CREATE TEMP TABLE tmp_daily_summary (
    date DATE PRIMARY KEY,
    weight_kg NUMERIC(5,2),
    body_fat_pct NUMERIC(4,2),
    muscle_pct NUMERIC(4,2),
    water_pct NUMERIC(4,2),
    fat_free_mass_kg NUMERIC(5,2),
    fat_mass_kg NUMERIC(5,2),
    muscle_mass_kg NUMERIC(5,2),
    water_mass_kg NUMERIC(5,2),
    bone_mass_kg NUMERIC(5,2),
    visceral_fat_index NUMERIC(5,2),
    bmr_kcal_day NUMERIC(8,2),
    nerve_health_score_feet NUMERIC(6,3),
    metabolic_age_years NUMERIC(5,2),
    steps DOUBLE PRECISION,
    exercise_minutes DOUBLE PRECISION,
    calories_active DOUBLE PRECISION,
    calories_resting DOUBLE PRECISION,
    stand_minutes DOUBLE PRECISION,
    distance_m DOUBLE PRECISION,
    flights_climbed DOUBLE PRECISION,
    respiratory_rate DOUBLE PRECISION,
    walking_hr_avg DOUBLE PRECISION,
    blood_oxygen_saturation DOUBLE PRECISION,
    wrist_temperature DOUBLE PRECISION,
    time_in_daylight DOUBLE PRECISION,
    cardio_recovery DOUBLE PRECISION,
    hr_resting DOUBLE PRECISION,
    hrv_sdnn_ms DOUBLE PRECISION,
    vo2_max DOUBLE PRECISION,
    hr_avg DOUBLE PRECISION,
    hr_max SMALLINT,
    hr_min SMALLINT,
    sleep_total_minutes NUMERIC,
    sleep_asleep_minutes NUMERIC,
    sleep_rem_minutes NUMERIC,
    sleep_deep_minutes NUMERIC,
    sleep_core_minutes NUMERIC,
    sleep_awake_minutes NUMERIC,
    body_age_years NUMERIC(6,1),
    body_age_delta_years NUMERIC(6,1),
    strength_volume_kg NUMERIC
  ) ON COMMIT DROP;

  INSERT INTO tmp_daily_summary(date)
  SELECT generate_series(p_start, p_end, interval '1 day')::date;

  UPDATE tmp_daily_summary AS tmp
     SET weight_kg = w.weight_kg,
         body_fat_pct = w.body_fat_pct,
         muscle_pct = w.muscle_pct,
         water_pct = w.water_pct,
         fat_free_mass_kg = w.fat_free_mass_kg,
         fat_mass_kg = w.fat_mass_kg,
         muscle_mass_kg = w.muscle_mass_kg,
         water_mass_kg = w.water_mass_kg,
         bone_mass_kg = w.bone_mass_kg,
         visceral_fat_index = w.visceral_fat_index,
         bmr_kcal_day = w.bmr_kcal_day,
         nerve_health_score_feet = w.nerve_health_score_feet,
         metabolic_age_years = w.metabolic_age_years
    FROM withings_daily AS w
   WHERE w.date = tmp.date
     AND w.date BETWEEN p_start AND p_end;

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
         exercise_minutes        = am.exercise_minutes,
         calories_active         = am.calories_active,
         calories_resting        = am.calories_resting,
         stand_minutes           = am.stand_minutes,
         distance_m              = am.distance_m,
         flights_climbed         = am.flights_climbed,
         respiratory_rate        = am.respiratory_rate,
         walking_hr_avg          = am.walking_hr_avg,
         blood_oxygen_saturation = am.blood_oxygen_saturation,
         wrist_temperature       = am.wrist_temperature,
         time_in_daylight        = am.time_in_daylight,
         cardio_recovery         = am.cardio_recovery,
         hr_resting              = am.resting_hr,
         hrv_sdnn_ms             = am.hrv_sdnn_ms,
         vo2_max                 = am.vo2_max
    FROM apple_metrics AS am
   WHERE am.record_date = tmp.date;

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
     SET sleep_total_minutes  = (sleep.total_sleep_hrs * 60)::NUMERIC,
         sleep_asleep_minutes = ((sleep.core_hrs + sleep.deep_hrs + sleep.rem_hrs) * 60)::NUMERIC,
         sleep_rem_minutes    = (sleep.rem_hrs * 60)::NUMERIC,
         sleep_deep_minutes   = (sleep.deep_hrs * 60)::NUMERIC,
         sleep_core_minutes   = (sleep.core_hrs * 60)::NUMERIC,
         sleep_awake_minutes  = (sleep.awake_hrs * 60)::NUMERIC
    FROM sleep
   WHERE sleep.date = tmp.date;

  UPDATE tmp_daily_summary AS tmp
     SET body_age_years       = b.body_age_years,
         body_age_delta_years = b.age_delta_years
    FROM body_age_daily AS b
   WHERE b.date = tmp.date
     AND b.date BETWEEN p_start AND p_end;

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

  INSERT INTO daily_summary AS ds (
      date,
      weight_kg,
      body_fat_pct,
      muscle_pct,
      water_pct,
      fat_free_mass_kg,
      fat_mass_kg,
      muscle_mass_kg,
      water_mass_kg,
      bone_mass_kg,
      visceral_fat_index,
      bmr_kcal_day,
      nerve_health_score_feet,
      metabolic_age_years,
      steps,
      exercise_minutes,
      calories_active,
      calories_resting,
      stand_minutes,
      distance_m,
      flights_climbed,
      respiratory_rate,
      walking_hr_avg,
      blood_oxygen_saturation,
      wrist_temperature,
      time_in_daylight,
      cardio_recovery,
      hr_resting,
      hrv_sdnn_ms,
      vo2_max,
      hr_avg,
      hr_max,
      hr_min,
      sleep_total_minutes,
      sleep_asleep_minutes,
      sleep_rem_minutes,
      sleep_deep_minutes,
      sleep_core_minutes,
      sleep_awake_minutes,
      body_age_years,
      body_age_delta_years,
      strength_volume_kg
  )
  SELECT
      date,
      weight_kg,
      body_fat_pct,
      muscle_pct,
      water_pct,
      fat_free_mass_kg,
      fat_mass_kg,
      muscle_mass_kg,
      water_mass_kg,
      bone_mass_kg,
      visceral_fat_index,
      bmr_kcal_day,
      nerve_health_score_feet,
      metabolic_age_years,
      steps,
      exercise_minutes,
      calories_active,
      calories_resting,
      stand_minutes,
      distance_m,
      flights_climbed,
      respiratory_rate,
      walking_hr_avg,
      blood_oxygen_saturation,
      wrist_temperature,
      time_in_daylight,
      cardio_recovery,
      hr_resting,
      hrv_sdnn_ms,
      vo2_max,
      hr_avg,
      hr_max,
      hr_min,
      sleep_total_minutes,
      sleep_asleep_minutes,
      sleep_rem_minutes,
      sleep_deep_minutes,
      sleep_core_minutes,
      sleep_awake_minutes,
      body_age_years,
      body_age_delta_years,
      strength_volume_kg
  FROM tmp_daily_summary
  ON CONFLICT (date) DO UPDATE SET
      weight_kg = EXCLUDED.weight_kg,
      body_fat_pct = EXCLUDED.body_fat_pct,
      muscle_pct = EXCLUDED.muscle_pct,
      water_pct = EXCLUDED.water_pct,
      fat_free_mass_kg = EXCLUDED.fat_free_mass_kg,
      fat_mass_kg = EXCLUDED.fat_mass_kg,
      muscle_mass_kg = EXCLUDED.muscle_mass_kg,
      water_mass_kg = EXCLUDED.water_mass_kg,
      bone_mass_kg = EXCLUDED.bone_mass_kg,
      visceral_fat_index = EXCLUDED.visceral_fat_index,
      bmr_kcal_day = EXCLUDED.bmr_kcal_day,
      nerve_health_score_feet = EXCLUDED.nerve_health_score_feet,
      metabolic_age_years = EXCLUDED.metabolic_age_years,
      steps = EXCLUDED.steps,
      exercise_minutes = EXCLUDED.exercise_minutes,
      calories_active = EXCLUDED.calories_active,
      calories_resting = EXCLUDED.calories_resting,
      stand_minutes = EXCLUDED.stand_minutes,
      distance_m = EXCLUDED.distance_m,
      flights_climbed = EXCLUDED.flights_climbed,
      respiratory_rate = EXCLUDED.respiratory_rate,
      walking_hr_avg = EXCLUDED.walking_hr_avg,
      blood_oxygen_saturation = EXCLUDED.blood_oxygen_saturation,
      wrist_temperature = EXCLUDED.wrist_temperature,
      time_in_daylight = EXCLUDED.time_in_daylight,
      cardio_recovery = EXCLUDED.cardio_recovery,
      hr_resting = EXCLUDED.hr_resting,
      hrv_sdnn_ms = EXCLUDED.hrv_sdnn_ms,
      vo2_max = EXCLUDED.vo2_max,
      hr_avg = EXCLUDED.hr_avg,
      hr_max = EXCLUDED.hr_max,
      hr_min = EXCLUDED.hr_min,
      sleep_total_minutes = EXCLUDED.sleep_total_minutes,
      sleep_asleep_minutes = EXCLUDED.sleep_asleep_minutes,
      sleep_rem_minutes = EXCLUDED.sleep_rem_minutes,
      sleep_deep_minutes = EXCLUDED.sleep_deep_minutes,
      sleep_core_minutes = EXCLUDED.sleep_core_minutes,
      sleep_awake_minutes = EXCLUDED.sleep_awake_minutes,
      body_age_years = EXCLUDED.body_age_years,
      body_age_delta_years = EXCLUDED.body_age_delta_years,
      strength_volume_kg = EXCLUDED.strength_volume_kg;
END;
$$;

COMMIT;
