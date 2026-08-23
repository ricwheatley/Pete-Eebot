CREATE TABLE IF NOT EXISTS nutrition_log (
    id BIGSERIAL PRIMARY KEY,
    client_event_id TEXT NULL,
    dedupe_fingerprint TEXT NOT NULL,
    eaten_at TIMESTAMPTZ NOT NULL,
    local_date DATE NOT NULL,
    protein_g NUMERIC(7,2) NOT NULL,
    carbs_g NUMERIC(7,2) NOT NULL,
    fat_g NUMERIC(7,2) NOT NULL,
    calories_est NUMERIC(8,2) NOT NULL,
    source TEXT NOT NULL,
    context TEXT NULL,
    confidence TEXT NOT NULL,
    meal_label TEXT NULL,
    notes TEXT NULL,
    raw_payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_nutrition_log_dedupe_fingerprint UNIQUE (dedupe_fingerprint)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_nutrition_log_client_event_id
    ON nutrition_log(client_event_id)
    WHERE client_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_nutrition_log_local_date
    ON nutrition_log(local_date);

CREATE INDEX IF NOT EXISTS idx_nutrition_log_eaten_at
    ON nutrition_log(eaten_at);

CREATE INDEX IF NOT EXISTS idx_nutrition_log_source_local_date
    ON nutrition_log(source, local_date);

COMMENT ON TABLE nutrition_log IS
'Immutable approximate nutrition events supplied by the GPT layer. Postgres is the source of truth.';

