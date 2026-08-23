-- Durable edge throttling and replay-safe GitHub deployment deliveries.

CREATE TABLE edge_rate_limit_counters (
    scope TEXT NOT NULL,
    subject_hash CHAR(64) NOT NULL,
    window_started_at TIMESTAMPTZ NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    next_allowed_at TIMESTAMPTZ,
    locked_until TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, subject_hash),
    CONSTRAINT ck_edge_rate_limit_scope_not_blank CHECK (btrim(scope) <> ''),
    CONSTRAINT ck_edge_rate_limit_subject_hash CHECK (subject_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_edge_rate_limit_event_count_nonnegative CHECK (event_count >= 0)
);

CREATE INDEX idx_edge_rate_limit_updated_at
    ON edge_rate_limit_counters(updated_at);

CREATE TABLE github_webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    repository_id BIGINT NOT NULL,
    event_name TEXT NOT NULL,
    ref_name TEXT NOT NULL,
    commit_sha CHAR(40) NOT NULL,
    job_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    failure_reason TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    handled_at TIMESTAMPTZ,
    CONSTRAINT ck_github_delivery_id_not_blank CHECK (btrim(delivery_id) <> ''),
    CONSTRAINT ck_github_repository_id_positive CHECK (repository_id > 0),
    CONSTRAINT ck_github_delivery_event_push CHECK (event_name = 'push'),
    CONSTRAINT ck_github_delivery_sha CHECK (commit_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT uq_github_signed_deploy_event UNIQUE (
        repository_id, event_name, ref_name, commit_sha
    ),
    CONSTRAINT ck_github_delivery_status CHECK (
        status IN ('accepted', 'dispatched', 'ignored', 'failed')
    )
);

CREATE INDEX idx_github_webhook_deliveries_received_at
    ON github_webhook_deliveries(received_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pete_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE edge_rate_limit_counters TO pete_user;
        GRANT SELECT, INSERT, UPDATE ON TABLE github_webhook_deliveries TO pete_user;
    END IF;
END
$$;
