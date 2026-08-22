# Optional Multi-Profile Migration Note

Phase 5.3 adds an optional coached-person profile abstraction. Browser `auth_users`
still represent people who can access the UI; `user_profiles` represent the
athlete/person whose training, health, and nutrition context is being viewed.

## Compatibility

- Existing single-user behavior remains the default.
- Existing source tables, plans, nutrition logs, and summary views are not
  rewritten and are not profile-scoped by this migration.
- If no database profile is configured, application services resolve the default
  profile from the existing `USER_DATE_OF_BIRTH`, `USER_HEIGHT_CM`,
  `USER_GOAL_WEIGHT_KG`, and `USER_TIMEZONE` settings.
- The migration inserts a `default` profile shell. Any missing database profile
  fields continue to fall back to the existing environment settings.
- Optional API profile selection is available on goal/coach state reads through
  the `profile` query parameter, but current shared data remains the same unless
  later migrations add profile keys to source tables.

## Authorization semantics

Profile-derived metadata is resolved with an explicit authenticated principal at
the application-service boundary:

- `owner` browser users may read every active profile;
- `operator` and `read_only` browser users may read only profiles joined to them
  through `auth_user_profiles`;
- when a non-owner omits `profile`, Pete selects the assigned global default, or
  the first assigned active profile if the global default is not assigned;
- a non-owner with no assignment receives `404 profile_not_found`;
- an explicit missing slug and an existing but unassigned slug return the same
  `404 profile_not_found` response so the API does not disclose profile existence;
- the configured `PETEEEBOT_API_KEY` is a trusted machine client with the explicit
  `profiles:read:any` scope, preserving its existing access to all active profiles;
- trusted local CLI and orchestrator reads use named machine principals with the
  same read scope. They do not obtain access through a missing browser user.

Assignment-scoped lookups join `auth_user_profiles` to `user_profiles` in the
repository query. Application services require the principal even when invoked
outside FastAPI, so direct calls cannot bypass profile authorization.

Assign every non-owner browser user before expecting profile-derived console or
API reads to succeed. For example:

```sql
INSERT INTO auth_user_profiles (user_id, profile_id)
SELECT u.id, p.id
FROM auth_users AS u
CROSS JOIN user_profiles AS p
WHERE u.username_normalized = 'coach-reader'
  AND p.slug = 'default'
ON CONFLICT DO NOTHING;
```

An absent assignment is intentionally deny-by-default, including for users that
were created before this authorization hardening.

## Apply

Back up first, then apply the migration:

```bash
scripts/backup_db.sh
psql "$DATABASE_URL" -f migrations/20260515_add_user_profiles.sql
```

Smoke checks:

```bash
pete status
curl -sS -H "X-API-Key: $PETEEEBOT_API_KEY" \
  "http://127.0.0.1:8000/api/v1/goal_state"
curl -sS -H "X-API-Key: $PETEEEBOT_API_KEY" \
  "http://127.0.0.1:8000/api/v1/coach_state?date=$(date +%F)"
```

Expected result: machine-key responses include a `profile` object with slug
`default`, and the body-composition goal still reflects the existing `USER_*`
settings. Browser-session smoke tests must use a user assigned to that profile.

## Rollback

Code rollback is safe because existing workflows do not depend on profile tables.
If you need to remove the schema after rolling back the application:

```sql
DROP TABLE IF EXISTS auth_user_profiles CASCADE;
DROP TABLE IF EXISTS user_profiles CASCADE;
```

Do not drop these tables if you have already created additional profiles that you
need to preserve. Export them first:

```bash
psql "$DATABASE_URL" -c "\copy user_profiles TO 'user_profiles_backup.csv' CSV HEADER"
psql "$DATABASE_URL" -c "\copy auth_user_profiles TO 'auth_user_profiles_backup.csv' CSV HEADER"
```

## Future Profile-Scoped Data

This migration is deliberately non-invasive. Before storing multiple independent
athletes in one database, add explicit nullable `profile_id` columns and
backfills to the affected data tables, then tighten reads/writes to require a
resolved profile. Until that follow-up exists, treat non-default profiles as
metadata and access-control groundwork rather than isolated training datasets.
