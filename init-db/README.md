# Database initialization retired

This directory intentionally contains no executable `.sql` file. PostgreSQL or
Docker entrypoint initialization must never load a destructive schema snapshot.

Use the authoritative migration runner instead:

```bash
pete-schema status
pete-schema upgrade
pete-schema verify
```

Existing databases created by the retired reset snapshot use the exact,
non-destructive `pete-schema adopt-legacy-reset --confirm-database NAME`
procedure documented in `docs/schema_management.md`.

For an explicitly disposable local database only, the guarded reset workflow is:

```bash
PETEEEBOT_ALLOW_DEVELOPMENT_RESET=1 \
  pete-schema reset-development \
  --confirm-database pete_e_dev \
  --i-understand-this-destroys-data
```

The reset command refuses non-loopback hosts, database names that do not start
with `pete_e_dev` or `pete_e_test`, non-development/test environments, missing
confirmation, and a mismatched database name. It drops `public` and rebuilds it
from `migrations/`; the operation is not recoverable without a backup.
