-- Phase 5.3 optional coached-person profiles.
-- Auth users remain browser identities; user_profiles describe the athlete/person
-- whose data and plans are managed. Existing single-user tables are unchanged.

CREATE TABLE IF NOT EXISTS user_profiles (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    date_of_birth DATE,
    height_cm INTEGER,
    goal_weight_kg NUMERIC(6,2),
    timezone TEXT NOT NULL DEFAULT 'Europe/London',
    is_default BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_user_profiles_slug_not_blank CHECK (btrim(slug) <> ''),
    CONSTRAINT ck_user_profiles_slug_format CHECK (slug ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    CONSTRAINT ck_user_profiles_display_name_not_blank CHECK (btrim(display_name) <> ''),
    CONSTRAINT ck_user_profiles_height_positive CHECK (height_cm IS NULL OR height_cm > 0),
    CONSTRAINT ck_user_profiles_goal_weight_positive CHECK (goal_weight_kg IS NULL OR goal_weight_kg > 0),
    CONSTRAINT ck_user_profiles_timezone_not_blank CHECK (btrim(timezone) <> '')
);

COMMENT ON TABLE user_profiles IS 'Coached-person profiles. Optional foundation for future multi-profile data scoping.';

CREATE UNIQUE INDEX IF NOT EXISTS ux_user_profiles_single_default
    ON user_profiles (is_default)
    WHERE is_default = true;

CREATE TABLE IF NOT EXISTS auth_user_profiles (
    user_id BIGINT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    profile_id BIGINT NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, profile_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_user_profiles_profile_id
    ON auth_user_profiles(profile_id);

INSERT INTO user_profiles (slug, display_name, timezone, is_default)
VALUES ('default', 'Default profile', 'Europe/London', true)
ON CONFLICT (slug) DO UPDATE
SET is_default = true,
    updated_at = now();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pete_user') THEN
        GRANT ALL PRIVILEGES ON TABLE user_profiles, auth_user_profiles TO pete_user;
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO pete_user;
    END IF;
END $$;
