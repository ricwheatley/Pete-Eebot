BEGIN;

-- 0A) Align daily_summary view with body_age_daily column names
-- Existing view selects b.body_age_delta_years, but body_age_daily exposes age_delta_years.
-- This recreates the view using the correct column, preserving all other fields.
-- Baseline reference: body_age_daily DDL and sp_upsert_body_age. 
-- Also see original daily_summary in schema.sql.
DROP VIEW IF EXISTS daily_summary;

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
    -- fixed: use age_delta_years from body_age_daily
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

COMMENT ON VIEW daily_summary IS 'Central view aggregating daily health and fitness metrics from various sources.';

-- 0B) Assistance seeds - make inserts idempotent, no duplicates on reruns
-- The table already has a PK across (main_exercise_id, assistance_exercise_id).
-- We reassert a couple of key rows with ON CONFLICT DO NOTHING to keep seeds idempotent.
INSERT INTO assistance_pool (main_exercise_id, assistance_exercise_id)
VALUES
    (73, 538)  -- Bench -> Triceps Pressdown as example row that appeared twice in baseline seed
ON CONFLICT (main_exercise_id, assistance_exercise_id) DO NOTHING;

COMMIT;
