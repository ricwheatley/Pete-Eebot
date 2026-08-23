-- Command history is an audit log and may record queued/started events before
-- the corresponding application_jobs row exists. Keep job_id as indexed
-- correlation data, but do not enforce a blocking foreign key.

ALTER TABLE IF EXISTS web_console_command_history
    DROP CONSTRAINT IF EXISTS web_console_command_history_job_id_fkey;
