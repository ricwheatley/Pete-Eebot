-- Convert daily_summary to a materialised view with a unique index on (date)
-- Also fixes the body age delta alias to match body_age_daily.age_delta_years

-- 1) Drop whichever form exists
DROP MATERIALIZED VIEW IF EXISTS daily_summary;
DROP VIEW IF EXISTS daily_summary;

-- 2) Recreate as MATERIALIZED VIEW
CREATE MATERIALIZED VIEW daily_summary AS
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
    -- corrected to match body_age_daily.age_delta_years
    b.age_delta_years AS body_age_delta_years,
    COALESCE(SUM(gl.weight_kg * gl.reps), 0) AS strength_volume_kg
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
         b.body_age_years, b.age_delta_years;

COMMENT ON MATERIALIZED VIEW daily_summary
IS 'Materialised daily metrics view. Refresh after daily sync and before body-age upsert.';

-- 3) Unique index to enable REFRESH CONCURRENTLY
-- Note: CREATE INDEX CONCURRENTLY cannot run inside a transaction block; run as standalone if you need to.
CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_summary_date ON daily_summary(date);

-- 4) First refresh
-- If you created the index concurrently outside a transaction, you can use CONCURRENTLY here.
REFRESH MATERIALIZED VIEW daily_summary;
