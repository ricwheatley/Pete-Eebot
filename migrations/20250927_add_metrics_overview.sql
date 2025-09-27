-- Migration: Add or update the metrics_overview view
-- Date: 2025-09-27
-- Safe to run multiple times (uses DROP/CREATE OR REPLACE VIEW)


DROP VIEW IF EXISTS metrics_overview;

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