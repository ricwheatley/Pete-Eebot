ALTER TABLE IF EXISTS application_jobs
    ADD COLUMN IF NOT EXISTS worker_id TEXT,
    ADD COLUMN IF NOT EXISTS attempt_number INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ownership_token BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS abandon_reason TEXT,
    ADD COLUMN IF NOT EXISTS progress_summary JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE application_jobs DROP CONSTRAINT IF EXISTS ck_application_jobs_status;
ALTER TABLE application_jobs
    ADD CONSTRAINT ck_application_jobs_status CHECK (
        status IN ('pending','queued', 'running', 'succeeded', 'failed', 'timeout', 'abandoned', 'cancelled')
    );

CREATE INDEX IF NOT EXISTS idx_application_jobs_lease_expires_at ON application_jobs(lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_application_jobs_worker_id ON application_jobs(worker_id);
