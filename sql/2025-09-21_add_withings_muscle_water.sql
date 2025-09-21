BEGIN;

ALTER TABLE withings_daily
    ADD COLUMN IF NOT EXISTS muscle_pct NUMERIC(4,2);

ALTER TABLE withings_daily
    ADD COLUMN IF NOT EXISTS water_pct NUMERIC(4,2);

DROP MATERIALIZED VIEW IF EXISTS daily_summary;

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
    AVG(dm.value) FILTER (WHERE mt.name = 'resting_heart_rate')                 AS hr_resting
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
  am.steps, am.exercise_minutes, am.calories_active, am.calories_resting, am.stand_minutes, am.distance_m, am.hr_resting,
  dhr.hr_avg, dhr.hr_max, dhr.hr_min,
  dss.total_sleep_hrs, dss.core_hrs, dss.deep_hrs, dss.rem_hrs, dss.awake_hrs,
  b.body_age_years, b.age_delta_years;

CREATE UNIQUE INDEX ux_daily_summary_date ON daily_summary(date);
COMMENT ON MATERIALIZED VIEW daily_summary IS 'Materialised daily metrics view, sourcing Apple data from new normalized tables.';

COMMIT;
