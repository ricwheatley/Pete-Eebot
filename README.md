# Pete-Eebot

Pete-Eebot is a Python fitness coaching and health-data orchestration system. It syncs Apple Health exports from Dropbox, Withings measurements, and wger workout data into PostgreSQL, then generates readiness summaries, training plans, coaching messages, and Telegram updates.

The active runtime model is a native Python virtual environment with PostgreSQL running separately. Docker is used for PostgreSQL infrastructure only; the application itself is not currently packaged or deployed as a container image.

## Architecture

Pete-Eebot follows a layered architecture:

```text
pete_e/
  domain/            Business rules, entities, planning, validation, readiness logic
  application/       Use cases, orchestration services, jobs, workflow coordination
  infrastructure/    PostgreSQL, Dropbox, Withings, wger, Telegram, cron, adapters
  cli/               Typer command entrypoints exposed through the `pete` command
  api_routes/        FastAPI route modules and browser console surfaces
  migrations/        Authoritative ordered SQL history and checksum manifest
```

Supporting directories:

```text
init-db/             Safety notice; executable bootstrap SQL is intentionally retired
scripts/             Operational helpers for backup, auth checks, catalogue sync, reviews
docs/                Operator, API, deployment, planner, and observability notes
tests/               Unit, application, integration, and CLI coverage
```

The domain layer owns policy. The application layer coordinates workflows. Infrastructure isolates IO and external services. CLI and API surfaces call into the application layer.

## Current Deployment Model

Supported today:

- Local development: native Python virtualenv, with PostgreSQL available locally or through `docker compose up -d db`.
- Production direction: Ubuntu Linux host, GitHub-based deploys, PostgreSQL in Docker, app running from a native Python virtualenv under `systemd` or another managed runtime, and nginx as a TLS reverse proxy.
- Historical Raspberry Pi deployment: still useful as operational context, but not the current target architecture.

Not supported today:

- A production Pete-Eebot application Docker image.
- Docker Compose as an application runtime.
- Application containers as a deployment-time migration mechanism.

## First-Time Setup

### Prerequisites

- Python 3.11, 3.12, or 3.13
- uv 0.12.5 (the required version is enforced by `pyproject.toml`)
- PostgreSQL client tools (`psql`, `pg_dump`, `pg_restore`)
- Docker and Docker Compose if using the local PostgreSQL container
- Dropbox app credentials for Apple Health Auto Export files
- Withings API credentials
- wger API key
- Telegram bot token and chat ID if messaging is enabled

### 1. Create the Python environment

```bash
uv sync --frozen
```

For a production install, sync the runtime subset of the same lock into the
external application environment and install Pete-Eebot non-editably:

```bash
python3 -m venv venv
uv lock --check
UV_PROJECT_ENVIRONMENT="$PWD/venv" uv sync --frozen --no-dev --no-editable
uv pip check --python "$PWD/venv/bin/python"
```

`pyproject.toml` is the only dependency input and `uv.lock` is the generated,
hashed, cross-platform lock. See
[`docs/dependency_management.md`](docs/dependency_management.md) before changing
either dependency constraints or the lock.

`uv sync --no-editable` builds and installs the project as a normal distribution;
runtime JSON, CSV, templates, static assets, and migrations are read from that
installed package. To inspect the exact release artifacts directly:

```bash
uv build --out-dir dist
python -m pytest -q -m artifact
```

The artifact lane inspects both wheel and sdist contents, installs the wheel in
a temporary environment outside the checkout, changes to a non-repository
working directory, and exercises the CLI, API, phrases, cron, and migrations.

### 2. Configure environment

```bash
cp .env.sample .env
chmod 600 .env
```

Fill in the required values described in [Environment Variables](#environment-variables). Settings use initializer values first, then process environment variables, then the selected dotenv file, then model defaults. Database configuration follows the explicit rule documented under [PostgreSQL](#postgresql).

### 3. Start PostgreSQL for local development

```bash
docker compose up -d db
```

This starts PostgreSQL only. Run Pete-Eebot from the host virtualenv.

### 4. Initialize the database

For a new database, load `.env` and apply the authoritative migration history.
The command uses the validated `DATABASE_URL` or complete `POSTGRES_*` settings
and never prints the resolved connection string:

```bash
set -a
. ./.env
set +a

pete-schema status
pete-schema upgrade
pete-schema verify
```

Never run a migration file manually. Existing databases without a ledger must use
the backup-first verified baseline procedure in
[`docs/schema_management.md`](docs/schema_management.md); `upgrade` refuses to
touch a populated untracked database. The same guide includes the narrowly
fingerprinted adoption path for databases created by the retired reset snapshot.

### 5. Complete OAuth setup

Withings:

```bash
pete withings-auth
pete withings-code  # paste the short-lived code at the hidden prompt
pete refresh-withings
```

Dropbox:

1. Create a scoped Dropbox app.
2. Grant the read scopes needed for Apple Health metric and workout exports.
3. Generate a refresh token.
4. Set `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`, `DROPBOX_HEALTH_METRICS_DIR`, and `DROPBOX_WORKOUTS_DIR`.

### 6. Verify integrations

```bash
python -m scripts.check_auth
pete status
```

### 7. Seed wger catalogue data

```bash
python -m scripts.sync_wger_catalog
```

This refreshes the local `wger_exercise` catalogue and seeds supporting exercise metadata used by plan generation.

## Local Development

Common commands:

```bash
pete status
pete sync --days 1 --retries 1
pete ingest-apple
pete withings-sync --days 7
pete morning-report
pete message --summary
pete message --plan
```

Run the API locally:

```bash
uvicorn pete_e.api:app --host 127.0.0.1 --port 8000
```

Health checks:

```bash
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz?timeout=5
curl -fsS -H "X-API-Key: $PETEEEBOT_API_KEY" "http://127.0.0.1:8000/api/v1/status?timeout=5"
```

`/healthz` is process-only. `/readyz` checks only PostgreSQL connectivity and
authoritative schema compatibility (with a maximum five-second query timeout)
and never calls external providers. `/api/v1/status` requires the machine key
or an operator/owner session; its provider checks run in parallel, use a short
TTL cache, and consume the shared PostgreSQL rate limit.

Run tests:

```bash
python -m pytest -q -m unit
python -m pytest -q -m contract
python -m pytest -q -m artifact
```

The PostgreSQL lane is deliberately opt-in and accepts only a loopback DSN
whose database name starts with `pete_e_test` and whose user contains `test`.
See [docs/testing.md](docs/testing.md) for dependency setup, lane definitions,
the disposable database command, and full-suite validation.

## Production Deployment

The recommended production topology is:

- Ubuntu Linux host.
- Git checkout on the host.
- `.env`, virtualenv, backups, and deploy wrapper outside the Git checkout.
- PostgreSQL running in Docker with a persistent volume.
- Pete-Eebot API running from a native Python virtualenv.
- `systemd` managing the API process.
- nginx terminating TLS and proxying to Uvicorn on `127.0.0.1`.

Example layout:

```text
/opt/myapp/
  current -> releases/<active-release>
  releases/
  shared/
    .env
    .backup_key
    venv/
    runtime/
      withings/.withings_tokens.json
  scripts/
    deploy.sh       # Stable wrapper outside the checkout
  backups/
    postgres/
    secrets/
    cloud-staging/
```

The repository includes deploy scripts and systemd definitions in `pete_e/resources/`.
They are checkout-only operational artifacts and are intentionally not included
in the Python wheel or sdist. The phrase JSON and cron CSV in the same source
directory are allowlisted runtime package data.
Their production defaults target `/opt/myapp`; override `PROJECT_ROOT`,
`APP_ROOT`, `SHARED_ROOT`, `ENV_FILE`, and `VENV_ROOT` for a different Ubuntu
layout.

### Application service

Install the tracked API unit, independent deploy template, validated dispatch
helper, and narrow sudoers rule:

```bash
sudo bash /opt/myapp/current/pete_e/resources/install-systemd-units.sh
sudo systemd-analyze verify \
  /etc/systemd/system/peteeebot.service \
  /etc/systemd/system/peteeebot-deploy@.service
sudo visudo -cf /etc/sudoers.d/peteeebot-deploy
```

`peteeebot.service` explicitly uses `KillMode=control-group`. Deployment does
not run in that control group: each accepted job runs in
`peteeebot-deploy@<job-id>.service`, which has no `PartOf=` or `BindsTo=` link to
the API unit. Restarting the API therefore cannot kill the deployment worker.

Install and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now peteeebot.service
sudo systemctl status peteeebot.service
```

Do not bind Uvicorn to a public interface in production. Public access should go through nginx.

### Browser console owner

If the browser console is enabled, create the first owner account from the host shell after verifying schema head:

```bash
cd /opt/myapp/current
set -a
. /opt/myapp/shared/.env
set +a
pete-schema verify
pete bootstrap-owner --username admin --email admin@example.com --display-name "Admin"
```

The command prompts for a password and refuses to run once an active owner already exists.

### nginx reverse proxy

Minimal HTTPS reverse proxy shape:

```nginx
server {
    listen 80;
    server_name ops.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ops.example.com;

    ssl_certificate /etc/letsencrypt/live/ops.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ops.example.com/privkey.pem;

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        # This nginx host is the public edge. Discard caller-supplied XFF.
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
```

Set `PETEEEBOT_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128` for this
localhost proxy topology. With no trusted CIDRs, Pete-Eebot ignores forwarding
headers. If a load balancer is added before nginx, configure nginx
`set_real_ip_from` only for that balancer, select its documented real-IP header,
enable `real_ip_recursive on`, and continue overwriting application XFF with the
resolved `$remote_addr`. Do not restore `$proxy_add_x_forwarded_for` at the
internet-facing edge.

Set `client_max_body_size 256k` on both `/webhook` and `/api/v1/webhook`
locations. The application independently enforces
`PETEEEBOT_WEBHOOK_MAX_BODY_BYTES=262144` while streaming, so nginx is a first
line rather than the only size control.

Use route-specific longer timeouts only for trusted command endpoints that intentionally run long operations.

### GitHub deploy flow

The active webhook deploy chain is:

1. GitHub sends `POST /webhook` with `X-Hub-Signature-256`.
2. Pete-Eebot bounds the body, validates `GITHUB_WEBHOOK_SECRET`, then requires
   `push`, repository ID `PETEEEBOT_GITHUB_REPOSITORY_ID`, exact configured
   `refs/heads/main`, non-deletion, and a lowercase 40-hex `after` SHA.
3. The API inserts `X-GitHub-Delivery` and a unique identity for the signed
   repository/event/ref/SHA into the PostgreSQL delivery ledger before dispatch.
   Replays return the existing job and never enqueue, even if the unsigned
   delivery header is altered.
4. The API creates and fences a durable job/operation lock, then asks the
   root-owned dispatch helper to start `peteeebot-deploy@<job-id>.service`.
5. The independent worker atomically takes ownership with a higher fencing
   token and heartbeats the job and lock while it runs `DEPLOY_SCRIPT_PATH`.
6. The stable wrapper verifies the configured origin URL, fetches only main,
   requires the signed SHA to exist and be an ancestor of fetched main, and
   resets the checkout to that exact SHA.
7. The tracked deploy script installs the package, refreshes cron, sends a
   Telegram notification, and restarts `peteeebot.service`.
8. The independent worker survives that restart, records the terminal result,
   and removes exactly its own operation lock in the same database transaction.

Required deploy environment:

```bash
export GITHUB_WEBHOOK_SECRET="replace-with-shared-webhook-secret"
export PETEEEBOT_GITHUB_REPOSITORY_ID="1044067254"
export PETEEEBOT_GITHUB_DEPLOY_REF="refs/heads/main"
export PETEEEBOT_WEBHOOK_MAX_BODY_BYTES="262144"
export DEPLOY_SCRIPT_PATH="/opt/myapp/scripts/deploy.sh"
export PETEEEBOT_DEPLOY_GIT_REMOTE="origin"
export PETEEEBOT_DEPLOY_GIT_REMOTE_URL="https://github.com/ricwheatley/Pete-Eebot.git"
export PETEEEBOT_DEPLOY_UNIT_TEMPLATE="peteeebot-deploy@.service"
export PETEEEBOT_DEPLOY_DISPATCH_BIN="/usr/local/sbin/peteeebot-dispatch-deploy"
```

Copy the wrapper outside the checkout:

```bash
cp /opt/myapp/current/pete_e/resources/deploy-wrapper.sh /opt/myapp/scripts/deploy.sh
chmod 700 /opt/myapp/scripts/deploy.sh
```

If using `/opt/myapp`, set path overrides in the wrapper environment or edit the wrapper copy deliberately:

```bash
PROJECT_ROOT=/opt/myapp
APP_ROOT=/opt/myapp/current
VENV_ROOT=/opt/myapp/shared/venv
UV_BIN=/opt/myapp/shared/uv-tool/bin/uv
```

## Operational Workflows

### Sync and coaching

```bash
pete sync --days 3 --retries 3
pete morning-report --send
pete message --summary --send
pete message --trainer --send
pete message --plan --send
```

### Planning

```bash
pete plan --start-date 2026-06-01
pete lets-begin --start-date 2026-06-01
python -m scripts.run_sunday_review
```

`pete plan` creates the next 4-week block. `pete lets-begin` creates and exports a strength-test week. The Sunday review validates or rolls forward the active plan.

Standard plan generation has one duration contract across CLI, API, and browser console: four weeks. Omitting `weeks` selects `4`; an explicit unsupported duration is rejected before a background job is created. The separate `pete lets-begin` strength-test workflow remains a one-week plan.

Readiness adjustment keeps generated `baseline_sets`/`baseline_rir` separate
from exported effective `sets`/`rir`. Assessment is non-mutating; durable
application is keyed by plan week, policy, source snapshot, and baseline
prescription so retries and force-overwrites converge instead of compounding.
See [`docs/readiness_adjustments.md`](docs/readiness_adjustments.md).

### Telegram listener

The Telegram listener is intentionally short-lived and is designed to be called repeatedly by cron:

```bash
pete telegram --listen-once --limit 5 --timeout 25
```

Supported bot commands include `/summary`, `/sync`, and `/lets-begin`.

### Cron

The cron source of truth is `pete_e/resources/pete_crontab.csv`. Render and activate it for the current user:

```bash
cd /opt/myapp/current
set -a
. /opt/myapp/shared/.env
set +a
/opt/myapp/shared/venv/bin/python -m pete_e.infrastructure.cron_manager --write --activate --summary
```

Active jobs include daily sync and morning report, Sunday review, weekly plan message, Telegram polling, weekly backup, heartbeat check, and basic host resource logging. Disabled rows in the CSV reference historical scripts that are not present and should remain disabled until replaced.

### Health checks

CLI:

```bash
pete status
```

Local API:

```bash
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz?timeout=5
curl -fsS -H "X-API-Key: $PETEEEBOT_API_KEY" "http://127.0.0.1:8000/api/v1/status?timeout=5"
```

`/readyz` is the cheap public PostgreSQL/schema gate; `/api/v1/status` is the
operator-only cached and shared-rate-limited provider view.

Service:

```bash
systemctl is-active peteeebot.service
journalctl -u peteeebot.service -n 100 --no-pager
```

Heartbeat recovery:

```bash
python -m scripts.heartbeat_check
```

The heartbeat script checks `PETEEEBOT_SERVICE_NAME` with `systemctl`, attempts a restart when the service is down, logs the event, and sends Telegram alerts when configured.

### Logging

Production logs prefer `/var/log/pete_eebot/pete_history.log` when writable. If that path is unavailable, the app falls back to `~/pete_logs/pete_history.log`.

View logs through the CLI:

```bash
pete logs
pete logs SYNC 100
pete logs PLAN 100
pete logs API 100
pete logs JOB 100
```

Structured JSON logging is controlled by:

```bash
PETE_LOG_LEVEL=INFO
PETE_LOG_FORMAT=json
PETE_LOG_TO_CONSOLE=false
```

See `docs/logging_observability.md` for request IDs, job IDs, audit events, and Prometheus metrics.

### Backups and restore

Run a backup:

```bash
cd /opt/myapp/current
set -a
. /opt/myapp/shared/.env
set +a
PROJECT_ROOT=/opt/myapp ./scripts/backup_db.sh
```

The backup script creates:

```text
backups/postgres/latest.dump
backups/secrets/.env.latest
backups/secrets/.withings_tokens.json.latest
```

It also prunes old local backups based on `RETENTION_WEEKS`.

Optional encrypted Dropbox upload:

```bash
BACKUP_CLOUD_UPLOAD=1
DROPBOX_BACKUP_DIR=/Pete-Eebot Backups
BACKUP_ENCRYPTION_KEY_FILE=/opt/myapp/shared/.backup_key
```

Decrypt a cloud backup:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in postgres_latest.enc \
  -out latest.dump \
  -pass file:/opt/myapp/shared/.backup_key
```

Restore a dump:

```bash
set -a
. /opt/myapp/shared/.env
set +a
export PGPASSWORD="$POSTGRES_PASSWORD"
pg_restore -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" --clean --if-exists --no-owner \
  /opt/myapp/backups/postgres/latest.dump
pete-schema verify
```

Keep backup encryption keys outside the Git checkout and in a password manager. A cloud backup is not restorable without the key or passphrase used to encrypt it.

## Environment Variables

Use `.env.sample` as the starting point.

### Core runtime

| Variable | Purpose |
| --- | --- |
| `ENVIRONMENT` | Runtime environment label. |
| `PETEEEBOT_ENV_FILE` | Explicit env file path, for example `/opt/myapp/shared/.env`. |
| `USER_DATE_OF_BIRTH`, `USER_HEIGHT_CM`, `USER_GOAL_WEIGHT_KG`, `USER_TIMEZONE` | Default coached-person profile facts. |
| `RUNNING_TARGET_RACE`, `RUNNING_RACE_DATE`, `RUNNING_TARGET_TIME`, `RUNNING_WEIGHT_LOSS_TARGET_KG` | Running goal context for planning. |
| `PETEEEBOT_DEFAULT_PROFILE_SLUG`, `PETEEEBOT_DEFAULT_PROFILE_NAME` | Optional default profile metadata. |

### PostgreSQL

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Optional explicit libpq/PostgreSQL connection string. When present, this is the authoritative value and its query options are preserved. |
| `PETEEEBOT_MIGRATOR_DATABASE_URL` | Optional deployment-only connection for the DDL-owning migrator role. Runtime readiness and repositories continue to use `DATABASE_URL`. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` | Component connection settings used only when `DATABASE_URL` is absent. User, password, and database name are percent-encoded when the URL is built; port defaults to `5432`. |
| `DB_HOST_OVERRIDE` | Optional typed replacement for `POSTGRES_HOST` when component configuration is used. |

Use either `DATABASE_URL` alone or the complete component set (`POSTGRES_PORT`
may be omitted to use `5432`). If both sources are present, all decoded user,
password, effective host, port, and database values must match; otherwise
startup fails instead of choosing a database silently. A matching explicit URL
wins so parameters such as `sslmode` and `connect_timeout` survive. A partial
component set is invalid even when a URL is present: remove the unused
components or provide the complete matching set. Process environment values
override dotenv values field by field, so a process override that creates a
mixed/conflicting configuration also fails clearly.

For local Compose, `POSTGRES_*` configures the database container independently
of the application. If the application uses an explicit URL, ensure it targets
the intended Compose database. Explicit URLs containing reserved characters
must already be percent-encoded; component configuration performs that encoding
automatically. Connection strings and `POSTGRES_PASSWORD` are redacted in
Settings representations and must not be logged.

### Dropbox and Apple Health

| Variable | Purpose |
| --- | --- |
| `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN` | Dropbox OAuth credentials. |
| `DROPBOX_HEALTH_METRICS_DIR`, `DROPBOX_WORKOUTS_DIR` | Dropbox folders containing Apple Health export files. |
| `DROPBOX_BACKUP_DIR`, `DROPBOX_BACKUP_TIMEOUT` | Optional Dropbox backup upload settings. |

### Withings

| Variable | Purpose |
| --- | --- |
| `WITHINGS_CLIENT_ID`, `WITHINGS_CLIENT_SECRET`, `WITHINGS_REDIRECT_URI` | Withings OAuth app settings. |
| `WITHINGS_REFRESH_TOKEN` | Initial refresh token; runtime tokens are persisted by the Withings client. |
| `WITHINGS_TOKEN_FILE` | Explicit runtime Withings token file, for example `/opt/myapp/shared/runtime/withings/.withings_tokens.json`. |
| `WITHINGS_ALERT_REAUTH` | Enables reauthorization alerts when token checks fail. |

### wger

| Variable | Purpose |
| --- | --- |
| `WGER_API_KEY` | wger API key. |
| `WGER_BASE_URL`, `WGER_USERNAME`, `WGER_PASSWORD` | Optional wger API/auth overrides. |
| `WGER_TIMEOUT`, `WGER_MAX_RETRIES`, `WGER_BACKOFF_BASE` | wger client retry controls. |
| `WGER_DRY_RUN`, `WGER_FORCE_OVERWRITE`, `WGER_EXPORT_DEBUG`, `WGER_EXPAND_STRETCH_ROUTINES` | Export behavior controls. |
| `WGER_BLAZE_MODE`, `WGER_ROUTINE_PREFIX` | wger routine export customization. |

### Telegram

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | Bot credentials for messages and alerts. |

### API, console, and security

| Variable | Purpose |
| --- | --- |
| `PETEEEBOT_API_KEY` | Machine API key sent as `X-API-Key`. |
| `PETEEEBOT_SESSION_COOKIE_NAME`, `PETEEEBOT_CSRF_COOKIE_NAME`, `PETEEEBOT_SESSION_COOKIE_DOMAIN`, `PETEEEBOT_SESSION_COOKIE_SECURE`, `PETEEEBOT_SESSION_COOKIE_SAMESITE` | Browser session cookie controls. |
| `PETEEEBOT_CORS_ALLOWED_ORIGINS`, `PETEEEBOT_ENABLE_HSTS` | Browser/API security settings. |
| `PETEEEBOT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS`, `PETEEEBOT_LOGIN_RATE_LIMIT_WINDOW_SECONDS`, `PETEEEBOT_LOGIN_LOCKOUT_SECONDS`, `PETEEEBOT_LOGIN_BACKOFF_BASE_SECONDS` | Login throttling controls. |
| `PETEEEBOT_COMMAND_RATE_LIMIT_MAX_REQUESTS`, `PETEEEBOT_COMMAND_RATE_LIMIT_WINDOW_SECONDS` | Command endpoint rate limits. |
| `PETEEEBOT_SYNC_TIMEOUT_SECONDS`, `PETEEEBOT_PROCESS_TIMEOUT_SECONDS` | Long-running command timeouts. |
| `PETEEEBOT_JOB_LEASE_SECONDS`, `PETEEEBOT_JOB_HEARTBEAT_SECONDS`, `PETEEEBOT_JOB_RECOVERY_SECONDS` | Fenced job lease, heartbeat cadence (less than half the lease), and periodic recovery cadence. |
| `GITHUB_WEBHOOK_SECRET`, `DEPLOY_SCRIPT_PATH`, `PETEEEBOT_DEPLOY_UNIT_TEMPLATE`, `PETEEEBOT_DEPLOY_DISPATCH_BIN`, `PETEEEBOT_DEPLOY_DISPATCH_TIMEOUT_SECONDS`, `PETEEEBOT_CLI_BIN` | GitHub webhook deployment, independent systemd dispatch, and absolute `pete` CLI path. |

### Runtime package data

| Variable | Purpose |
| --- | --- |
| `PETEEEBOT_PHRASES_FILE` | Optional external phrase JSON override; the wheel-bundled JSON is the default. |
| `PETEEEBOT_CRON_SOURCE` | Optional external cron CSV override; the wheel-bundled schedule is the default. |
| `PETEEEBOT_CRONTAB_OUTPUT` | External generated-crontab target; defaults under the user's state directory. |
| `PETEEEBOT_MIGRATIONS_DIR` | Optional reviewed external migration-set override; bundled authoritative migrations are the default. |

### Logging, alerting, and monitoring

| Variable | Purpose |
| --- | --- |
| `PETE_LOG_LEVEL`, `PETE_LOG_FORMAT`, `PETE_LOG_TO_CONSOLE` | Application logging controls. |
| `PETEEEBOT_ALERT_TELEGRAM_ENABLED`, `PETEEEBOT_ALERT_DEDUPE_SECONDS` | Telegram delivery (default `true`) and non-negative dedupe window in seconds (default `3600`; `0` disables dedupe). |
| `PETEEEBOT_STALE_INGEST_ALERT_DAYS`, `PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD` | Stale-ingest threshold of at least one day (default `3`) and non-negative consecutive-failure threshold (default `3`; `0` disables repeated-failure alerts). |
| `APPLE_MAX_STALE_DAYS` | Legacy Apple stale-data threshold. It remains the effective alert threshold when `PETEEEBOT_STALE_INGEST_ALERT_DAYS` is absent; the new setting wins when both are supplied. |
| `PETEEEBOT_SERVICE_NAME`, `PETEEEBOT_RESTART_TIMEOUT_SECONDS`, `PETEEEBOT_SERVICE_MONITOR_LOG`, `SYSTEMCTL_BIN`, `SUDO_BIN` | Heartbeat and service recovery settings. |

### Backups and DNS

| Variable | Purpose |
| --- | --- |
| `BACKUP_ROOT`, `DB_BACKUP_DIR`, `SECRETS_BACKUP_DIR`, `CLOUD_STAGING_DIR` | Backup locations. |
| `BACKUP_CLOUD_UPLOAD`, `BACKUP_ENCRYPTION_KEY_FILE`, `BACKUP_ENCRYPTION_PASSPHRASE`, `RETENTION_WEEKS` | Backup upload, encryption, and retention controls. |
| `DUCKDNS_DOMAIN`, `DUCKDNS_TOKEN` | Optional DuckDNS updater settings. |

### Planning feature flags

| Variable | Purpose |
| --- | --- |
| `PETEEEBOT_PLANNER_FEATURE_FLAGS` | Explicit planner experiment toggles. Defaults to empty. |

## Production Recommendations

- Run Uvicorn on `127.0.0.1` behind nginx with TLS.
- Allow public inbound traffic only on `80/tcp` and `443/tcp`; keep PostgreSQL and Uvicorn off public interfaces.
- Store `.env`, Withings token files, backup keys, and deploy scripts outside the Git checkout with owner-only permissions.
- Use a dedicated Unix user for the application.
- Disable SSH password login, use key-based authentication, and restrict sudo privileges to the commands needed for deployment and service restart.
- Keep PostgreSQL data in a named Docker volume or explicitly managed host volume.
- Run `scripts/backup_db.sh` on a schedule and periodically test restore into a disposable database.
- Require `pete-schema verify` after every restore and before every service restart.
- Configure log rotation for `/var/log/pete_eebot`.
- Keep `PETEEEBOT_API_KEY`, `GITHUB_WEBHOOK_SECRET`, Telegram credentials, Dropbox credentials, Withings credentials, and backup encryption keys in a password manager.
- Rotate API and webhook secrets after suspected exposure or client changes.
- Complete `docs/production_readiness_checklist.md` before exposing the service to the internet.

## Historical Deployment

Earlier Raspberry Pi production operation kept secrets, the virtualenv, deploy scripts, and the checkout under a home-directory tree. The supported production baseline is now the `/opt/myapp` layout above; production scripts and cron entries should not depend on a home-directory checkout or an in-repo virtualenv.

## Developer Notes

Useful docs:

- `docs/operator_guide.md`
- `docs/schema_management.md`
- `docs/runtime_deploy_runbook.md`
- `docs/logging_observability.md`
- `docs/api_endpoint_inventory.md`
- `docs/production_readiness_checklist.md`
- `docs/credential_incident_runbook.md`
- `docs/planner_feature_flags.md`
- `docs/unified_global_planner.md`
- `docs/pete_coach_openapi.yaml`
- `CONTRIBUTING.md`

Contribution workflow:

1. Create a feature branch.
2. Add or update tests for behavior changes.
3. Run `pytest` and relevant targeted checks.
4. Run `python scripts/test_secret_scanner.py` with the pinned Gitleaks version documented in `CONTRIBUTING.md`.
5. Document operational impact in the PR, including new environment variables, migrations, scheduling changes, or deployment changes.

## Disclaimer

Pete-Eebot provides informational coaching assistance and automation. It is not a medical device and should not replace qualified medical advice.
