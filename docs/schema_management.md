# Authoritative database schema management

Pete-Eebot uses a PostgreSQL-specific ordered SQL runner. `migrations/manifest.json`
is the authoritative order and checksum list, and `petee_schema_migrations` is the
database-side revision ledger. Alembic was evaluated but not selected: the project
has one linear, hand-written PostgreSQL SQL history and no ORM metadata, so Alembic
would add a dependency while still wrapping the same raw SQL. The smaller runner
provides the required locking, transaction, checksum, adoption, and verification
guarantees directly.

Do not apply files in `migrations/` with `psql`. Do not edit an applied migration.
Add a new ordered SQL file and manifest entry instead.
Checksums use UTF-8 SQL with line endings normalized to LF, so the same revision
identity is preserved across Windows and Linux checkouts.

## Commands

All commands read the application target from the validated `DATABASE_URL` or
`POSTGRES_*` settings. Write commands use `PETEEEBOT_MIGRATOR_DATABASE_URL` when
it is set, allowing the runtime role to remain DML-only.

```bash
pete-schema status
pete-schema preflight
pete-schema upgrade
pete-schema verify
```

- `status` is read-only and reports empty, untracked, stale, invalid, incomplete,
  or head state.
- `preflight` is read-only and permits only an empty database or a valid recorded
  prefix. Deployments stop here for untracked, reordered, modified, or incomplete
  history.
- `upgrade` takes a PostgreSQL advisory lock and applies each pending file in its
  own transaction. The ledger insert is in that same transaction and therefore
  cannot be recorded after a failed or partial migration.
- `verify` uses the runtime role and requires the exact manifest head plus the
  essential auth, session, profile, jobs, web history, nutrition, planning, and
  readiness schema markers.

An empty database needs only:

```bash
pete-schema upgrade
pete-schema verify
```

`upgrade --revision REVISION` is available for release testing. Downgrades are
not supported. The previous-release test revision is recorded explicitly in the
manifest rather than inferred from filenames.

## Existing installation adoption

Never point the development reset command at an existing installation. Adoption
does not replay SQL and does not drop application objects:

1. Stop writes or enter a maintenance window. Record the database host, exact
   database name, deployed Git SHA, and SQL files previously applied.
2. Run `pete-schema status`. An existing installation without a ledger should
   report `untracked`; this is read-only.
3. Take a `pg_dump` backup with `scripts/backup_db.sh`, verify its checksum, and
   restore it into a disposable database. Perform the following checks on that
   restored copy first.
4. Determine the last fully applied revision from deployment records and schema
   inspection. Do not guess. The baseline command checks cumulative structural
   markers and rejects missing or later/non-linear markers.
5. Stamp the confirmed revision with the migrator role:

   ```bash
   pete-schema baseline \
     --revision 20260820_add_readiness_adjustment_idempotency \
     --confirm-database exact_database_name
   ```

6. Run `pete-schema status`, `pete-schema upgrade`, and `pete-schema verify` on
   the restored copy. Check representative retained auth, profile, job, nutrition,
   and plan data.
7. Repeat the exact baseline and upgrade during the production maintenance window,
   then start the new application only after `verify` succeeds.

A fully current legacy installation that already contains the reconciliation
markers may be baselined directly at `head`. A partially applied or non-linear
installation is deliberately rejected. Repair it on a restored clone and create
a reviewed forward reconciliation migration; never stamp through uncertainty.

Baseline checks prove structural milestones, not the historical provenance of
every function body or past data update. Deployment records, backup rehearsal,
and application smoke tests remain required evidence for legacy adoption.

### Retired reset-snapshot installations

The retired `init-db/schema.sql` was not a linear head. Its final repository
version already contained `training_cycle` and `training_plans.metadata`, but it
omitted four nutrition columns and seven application-job lease/recovery columns
from earlier migrations. It therefore cannot truthfully be stamped at any normal
linear revision.

For a database known to have been created from that exact snapshot, rehearse on a
restored copy and use the dedicated adoption profile:

```bash
pete-schema adopt-legacy-reset --confirm-database exact_database_name
pete-schema verify
```

This command requires the exact database-name confirmation, fingerprints every
schema milestone, and rejects partial or different shapes. In one transaction it
applies only the three omitted historical revisions, records those as executed,
records already-present revisions as baseline, and verifies head. It neither
replays the already-present revisions nor drops application objects. If the
fingerprint fails, stop and create a reviewed forward reconciliation on a restored
clone; do not weaken the checks or guess a stamp.

## Roles and privileges

The runtime account needs normal application DML and `SELECT` on
`public.petee_schema_migrations`; it does not need schema `CREATE` or unrestricted
DDL. The migrator account must own the migrated objects, or be a member of the
role that owns them, because PostgreSQL requires ownership for `ALTER TABLE` and
function replacement. A typical installation uses a non-login schema-owner role,
a login migrator that can assume it, and a separate runtime login.

When introducing a separate migrator to an existing database, review object
ownership on a restored copy. After the ledger exists, grant only its read access
to the runtime role, for example:

```sql
GRANT SELECT ON public.petee_schema_migrations TO pete_runtime;
```

Do not put the migrator URL into the systemd application environment unless the
same protected environment file is also used by deployment; the application
always connects with `DATABASE_URL`.

## Transactions, failure, and recovery

All current revisions use PostgreSQL transactional DDL. Migration files must not
contain `BEGIN`, `COMMIT`, `ROLLBACK`, `VACUUM`, or concurrent-index operations;
the manifest validator rejects them. If a future operation cannot run in a
transaction, design and document a resumable two-phase rollout and extend the
runner explicitly rather than bypassing it.

On failure, PostgreSQL rolls back both the migration SQL and ledger insert. The
old service is left running and `deploy.sh` does not refresh cron or restart the
service. Fix or replace only the unapplied revision, rerun on a restored copy,
then rerun deployment. Never change a revision already present in any ledger.

There is no automatic schema downgrade. Rollback means one of:

- deploy the previous binary when the forward schema is backward compatible; or
- stop writes, restore the pre-upgrade dump, verify its ledger, then deploy the
  matching previous binary.

The tracked deployment runs a read-only preflight, creates a database backup by
default, upgrades, and verifies with the runtime role before restart.
`SCHEMA_BACKUP_BEFORE_UPGRADE=0` is an explicit emergency bypass and must be
recorded as accepted rollout risk.

## Development reset

Docker no longer auto-loads SQL. Start its PostgreSQL service, then upgrade:

```bash
docker compose up -d db
pete-schema upgrade
```

The only reset workflow is deliberately named and multiply guarded:

```bash
PETEEEBOT_ALLOW_DEVELOPMENT_RESET=1 \
  pete-schema reset-development \
  --confirm-database pete_e_dev \
  --i-understand-this-destroys-data
```

It accepts only loopback connections, development/test environments, and database
names beginning `pete_e_dev` or `pete_e_test`. It drops the `public` schema and
rebuilds empty-to-head. The exact database name must be repeated on the command
line. Data is recoverable only from a backup.
