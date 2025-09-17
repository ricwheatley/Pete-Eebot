BEGIN;

-- Add routine_id column if it doesn't exist already
ALTER TABLE wger_export_log
    ADD COLUMN IF NOT EXISTS routine_id INT;

-- Backfill from any previous successful responses
-- Wger's /routine/ POST returns an 'id' field for the routine object.
-- Our exporter stores that JSON in response_json, so extract it.
UPDATE wger_export_log
SET routine_id = (response_json->>'id')::int
WHERE routine_id IS NULL
  AND (response_json ? 'id');

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_wger_export_log_routine_id
    ON wger_export_log(routine_id);

COMMENT ON COLUMN wger_export_log.routine_id IS
    'The wger routine id created/updated for this plan/week, if known';

COMMIT;
