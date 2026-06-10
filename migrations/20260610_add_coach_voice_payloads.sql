-- Full structured payload audit trail for Ollama coach voice generation.

CREATE TABLE IF NOT EXISTS coach_voice_payloads (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    message_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    model TEXT,
    status TEXT NOT NULL,
    duration_ms INTEGER,
    request_payload JSONB NOT NULL,
    prompt_messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    response_text TEXT,
    fallback_text TEXT NOT NULL,
    final_text TEXT NOT NULL,
    error TEXT,
    CONSTRAINT ck_coach_voice_payloads_message_type_not_blank CHECK (btrim(message_type) <> ''),
    CONSTRAINT ck_coach_voice_payloads_schema_version_not_blank CHECK (btrim(schema_version) <> ''),
    CONSTRAINT ck_coach_voice_payloads_status_not_blank CHECK (btrim(status) <> '')
);

CREATE INDEX IF NOT EXISTS idx_coach_voice_payloads_created_at
    ON coach_voice_payloads(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_coach_voice_payloads_message_type_created_at
    ON coach_voice_payloads(message_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_coach_voice_payloads_status_created_at
    ON coach_voice_payloads(status, created_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pete_user') THEN
        GRANT ALL PRIVILEGES ON TABLE coach_voice_payloads TO pete_user;
        IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'coach_voice_payloads_id_seq') THEN
            GRANT ALL PRIVILEGES ON SEQUENCE coach_voice_payloads_id_seq TO pete_user;
        END IF;
    END IF;
END;
$$;
