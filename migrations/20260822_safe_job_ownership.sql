-- Fence every running job and operation lock with the same execution owner.

ALTER TABLE application_operation_locks
    ADD COLUMN IF NOT EXISTS worker_id TEXT,
    ADD COLUMN IF NOT EXISTS ownership_token BIGINT;

UPDATE application_jobs
SET status = 'abandoned',
    completed_at = COALESCE(completed_at, now()),
    abandon_reason = COALESCE(abandon_reason, 'ownership_migration'),
    failure_reason = COALESCE(failure_reason, 'ownership_migration'),
    result_summary = COALESCE(
        result_summary,
        'Operation abandoned because its legacy running row had no valid owner.'
    ),
    updated_at = now()
WHERE status = 'running'
  AND (
      worker_id IS NULL
      OR btrim(worker_id) = ''
      OR ownership_token <= 0
      OR last_heartbeat_at IS NULL
      OR lease_expires_at IS NULL
  );

UPDATE application_operation_locks AS operation_lock
SET worker_id = job.worker_id,
    ownership_token = job.ownership_token
FROM application_jobs AS job
WHERE job.id = operation_lock.job_id
  AND job.status = 'running'
  AND job.worker_id IS NOT NULL
  AND job.ownership_token > 0;

DELETE FROM application_operation_locks
WHERE job_id IS NULL
   OR worker_id IS NULL
   OR btrim(worker_id) = ''
   OR ownership_token IS NULL
   OR ownership_token <= 0;

ALTER TABLE application_operation_locks
    ALTER COLUMN job_id SET NOT NULL,
    ALTER COLUMN worker_id SET NOT NULL,
    ALTER COLUMN ownership_token SET NOT NULL;

ALTER TABLE application_operation_locks
    DROP CONSTRAINT IF EXISTS application_operation_locks_job_id_fkey,
    DROP CONSTRAINT IF EXISTS ck_application_operation_locks_worker_id_not_blank,
    DROP CONSTRAINT IF EXISTS ck_application_operation_locks_ownership_token_positive;

ALTER TABLE application_operation_locks
    ADD CONSTRAINT application_operation_locks_job_id_fkey
        FOREIGN KEY (job_id) REFERENCES application_jobs(id) ON DELETE CASCADE,
    ADD CONSTRAINT ck_application_operation_locks_worker_id_not_blank
        CHECK (btrim(worker_id) <> ''),
    ADD CONSTRAINT ck_application_operation_locks_ownership_token_positive
        CHECK (ownership_token > 0);

ALTER TABLE application_jobs
    DROP CONSTRAINT IF EXISTS ck_application_jobs_ownership_token_non_negative,
    DROP CONSTRAINT IF EXISTS ck_application_jobs_running_owner;

ALTER TABLE application_jobs
    ADD CONSTRAINT ck_application_jobs_ownership_token_non_negative
        CHECK (ownership_token >= 0),
    ADD CONSTRAINT ck_application_jobs_running_owner CHECK (
        status <> 'running'
        OR (
            worker_id IS NOT NULL
            AND btrim(worker_id) <> ''
            AND ownership_token > 0
            AND last_heartbeat_at IS NOT NULL
            AND lease_expires_at IS NOT NULL
        )
    );

CREATE INDEX IF NOT EXISTS idx_application_operation_locks_owner
    ON application_operation_locks(job_id, worker_id, ownership_token);
