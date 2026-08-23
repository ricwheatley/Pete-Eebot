-- Reconcile schema changes that were previously added only to the reset snapshot.
-- The authoritative migration runner owns the transaction boundary.

ALTER TABLE training_plans
    ADD COLUMN metadata JSONB;

CREATE TABLE training_cycle (
    id SERIAL PRIMARY KEY,
    start_date DATE NOT NULL,
    current_week INT NOT NULL,
    current_block INT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE training_cycle IS
    'Tracks the state of the 13-week 5/3/1 macrocycle.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pete_user') THEN
        GRANT ALL PRIVILEGES ON TABLE training_cycle TO pete_user;
        GRANT ALL PRIVILEGES ON SEQUENCE training_cycle_id_seq TO pete_user;
    END IF;
END;
$$;
