-- Optional browser MFA/TOTP state for owner/operator users.

ALTER TABLE auth_users
    ADD COLUMN IF NOT EXISTS mfa_secret TEXT,
    ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS mfa_recovery_code_hashes JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_auth_users_mfa_enabled
    ON auth_users(mfa_enabled)
    WHERE mfa_enabled = true;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pete_user') THEN
        GRANT ALL PRIVILEGES ON TABLE auth_users TO pete_user;
    END IF;
END;
$$;
