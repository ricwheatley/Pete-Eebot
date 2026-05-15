-- Durable application jobs for web console command execution.

CREATE TABLE IF NOT EXISTS application_jobs (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    requester_user_id BIGINT REFERENCES auth_users(id) ON DELETE SET NULL,
    requester_username TEXT,
    auth_scheme TEXT,
    status TEXT NOT NULL,
    request_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    request_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    exit_code INTEGER,
    result_summary TEXT,
    stdout_summary TEXT,
    stderr_summary TEXT,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_application_jobs_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'timeout')
    ),
    CONSTRAINT ck_application_jobs_operation_not_blank CHECK (btrim(operation) <> ''),
    CONSTRAINT ck_application_jobs_request_id_not_blank CHECK (btrim(request_id) <> ''),
    CONSTRAINT ck_application_jobs_correlation_id_not_blank CHECK (btrim(correlation_id) <> '')
);

ALTER TABLE IF EXISTS application_jobs
    ADD COLUMN IF NOT EXISTS auth_scheme TEXT;

CREATE INDEX IF NOT EXISTS idx_application_jobs_created_at
    ON application_jobs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_application_jobs_status
    ON application_jobs(status);

CREATE INDEX IF NOT EXISTS idx_application_jobs_correlation_id
    ON application_jobs(correlation_id);

CREATE INDEX IF NOT EXISTS idx_application_jobs_requester_user_id
    ON application_jobs(requester_user_id);

CREATE TABLE IF NOT EXISTS web_console_command_history (
    id BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    job_id TEXT REFERENCES application_jobs(id) ON DELETE SET NULL,
    requester_user_id BIGINT REFERENCES auth_users(id) ON DELETE SET NULL,
    requester_username TEXT,
    auth_scheme TEXT,
    command TEXT NOT NULL,
    outcome TEXT NOT NULL,
    safe_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    client_identity TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_web_console_command_history_request_id_not_blank CHECK (btrim(request_id) <> ''),
    CONSTRAINT ck_web_console_command_history_correlation_id_not_blank CHECK (btrim(correlation_id) <> ''),
    CONSTRAINT ck_web_console_command_history_command_not_blank CHECK (btrim(command) <> ''),
    CONSTRAINT ck_web_console_command_history_outcome_not_blank CHECK (btrim(outcome) <> '')
);

CREATE INDEX IF NOT EXISTS idx_web_console_command_history_created_at
    ON web_console_command_history(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_web_console_command_history_request_id
    ON web_console_command_history(request_id);

CREATE INDEX IF NOT EXISTS idx_web_console_command_history_job_id
    ON web_console_command_history(job_id);

CREATE INDEX IF NOT EXISTS idx_web_console_command_history_command_outcome
    ON web_console_command_history(command, outcome, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_web_console_command_history_requester_user_id
    ON web_console_command_history(requester_user_id);

CREATE TABLE IF NOT EXISTS application_operation_locks (
    lock_name TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    job_id TEXT REFERENCES application_jobs(id) ON DELETE SET NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_application_operation_locks_lock_name_not_blank CHECK (btrim(lock_name) <> ''),
    CONSTRAINT ck_application_operation_locks_operation_not_blank CHECK (btrim(operation) <> '')
);

CREATE INDEX IF NOT EXISTS idx_application_operation_locks_job_id
    ON application_operation_locks(job_id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pete_user') THEN
        GRANT ALL PRIVILEGES ON TABLE application_jobs TO pete_user;
        GRANT ALL PRIVILEGES ON TABLE web_console_command_history TO pete_user;
        IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'web_console_command_history_id_seq') THEN
            GRANT ALL PRIVILEGES ON SEQUENCE web_console_command_history_id_seq TO pete_user;
        END IF;
        GRANT ALL PRIVILEGES ON TABLE application_operation_locks TO pete_user;
    END IF;
END;
$$;
