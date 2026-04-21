BEGIN;

CREATE TABLE IF NOT EXISTS withings_measure_groups (
    grpid BIGINT PRIMARY KEY,
    day DATE NOT NULL,
    measured_at TIMESTAMPTZ NOT NULL,
    created_at_source TIMESTAMPTZ,
    modified_at_source TIMESTAMPTZ,
    category INT,
    attrib INT,
    comment TEXT,
    device_id TEXT,
    hash_device_id TEXT,
    model TEXT,
    model_id INT,
    timezone_name TEXT,
    raw_payload_json JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE withings_measure_groups IS
    'Stores every raw Withings measure group returned by getmeas so newly exposed scale metrics are retained without schema changes.';

CREATE INDEX IF NOT EXISTS idx_withings_measure_groups_day
    ON withings_measure_groups(day);

COMMIT;
