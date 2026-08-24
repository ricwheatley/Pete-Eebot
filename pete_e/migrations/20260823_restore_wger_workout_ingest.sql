-- Preserve stable upstream identity while leaving the existing consumer schema intact.
ALTER TABLE wger_logs
    ADD COLUMN IF NOT EXISTS wger_log_id TEXT,
    ADD COLUMN IF NOT EXISTS wger_session_id TEXT,
    ADD COLUMN IF NOT EXISTS performed_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS ux_wger_logs_source_id
    ON wger_logs (wger_log_id)
    WHERE wger_log_id IS NOT NULL;

COMMENT ON COLUMN wger_logs.wger_log_id IS
    'Stable UUID or legacy identifier returned by the wger workout-log API.';
COMMENT ON COLUMN wger_logs.wger_session_id IS
    'Workout-session identifier returned by wger when available.';
COMMENT ON COLUMN wger_logs.performed_at IS
    'Source workout-log timestamp retained in UTC; date is the coached-person local date.';
