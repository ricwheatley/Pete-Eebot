BEGIN;

-- ============================================================================
-- Add unique indexes to materialized views so they can be refreshed CONCURRENTLY
-- ============================================================================

-- plan_muscle_volume: unique per plan_id + week_number + muscle_id
CREATE UNIQUE INDEX IF NOT EXISTS ux_plan_muscle_volume
    ON plan_muscle_volume (plan_id, week_number, muscle_id);

-- actual_muscle_volume: unique per date + muscle_id
CREATE UNIQUE INDEX IF NOT EXISTS ux_actual_muscle_volume
    ON actual_muscle_volume (date, muscle_id);

-- daily_summary: should already exist from earlier migration, but ensure it is there
CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_summary_date
    ON daily_summary (date);

COMMIT;
