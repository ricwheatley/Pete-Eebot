-- Phase 2 auth primitives: browser users, sessions, and RBAC roles.

CREATE TABLE IF NOT EXISTS auth_roles (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    CONSTRAINT ck_auth_roles_name CHECK (name IN ('owner', 'operator', 'read_only'))
);

INSERT INTO auth_roles (name, description)
VALUES
    ('owner', 'Full administrative access, including user and security administration.'),
    ('operator', 'Can run operational workflows and manage day-to-day coach actions.'),
    ('read_only', 'Can view status, plans, logs, and summaries without making changes.')
ON CONFLICT (name) DO UPDATE
SET description = EXCLUDED.description;

CREATE TABLE IF NOT EXISTS auth_users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    username_normalized TEXT NOT NULL UNIQUE,
    email TEXT,
    email_normalized TEXT UNIQUE,
    display_name TEXT,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_auth_users_username_not_blank CHECK (btrim(username) <> ''),
    CONSTRAINT ck_auth_users_username_normalized_not_blank CHECK (btrim(username_normalized) <> '')
);

CREATE TABLE IF NOT EXISTS auth_user_roles (
    user_id BIGINT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    role_name TEXT NOT NULL REFERENCES auth_roles(name),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_name)
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    ip_address INET,
    user_agent TEXT,
    CONSTRAINT ck_auth_sessions_expires_after_created CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_auth_user_roles_role_name
    ON auth_user_roles(role_name);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id
    ON auth_sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at
    ON auth_sessions(expires_at);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_active_token
    ON auth_sessions(token_hash)
    WHERE revoked_at IS NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pete_user') THEN
        GRANT ALL PRIVILEGES ON TABLE auth_roles, auth_users, auth_user_roles, auth_sessions TO pete_user;
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO pete_user;
    END IF;
END;
$$;
