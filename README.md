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
```

Supporting directories:

```text
init-db/             Base PostgreSQL schema bootstrap
migrations/          Manually applied SQL migrations
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
- Automatic migration management through Alembic or a migration runner.

## First-Time Setup

### Prerequisites

- Python 3.11+
- PostgreSQL client tools (`psql`, `pg_dump`, `pg_restore`)
- Docker and Docker Compose if using the local PostgreSQL container
- Dropbox app credentials for Apple Health Auto Export files
- Withings API credentials
- wger API key
- Telegram bot token and chat ID if messaging is enabled

### 1. Create the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
```

For a production install, keep dependency versions pinned and install the package without resolving extras:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

### 2. Configure environment

```bash
cp .env.sample .env
chmod 600 .env
```

Fill in the required values described in [Environment Variables](#environment-variables). The settings layer reads `.env` from the repository root and builds `DATABASE_URL` from the `POSTGRES_*` values.

### 3. Start PostgreSQL for local development

```bash
docker compose up -d db
```

This starts PostgreSQL only. Run Pete-Eebot from the host virtualenv.

### 4. Initialize the database

For a new database:

```bash
set -a
. ./.env
set +a
psql "$DATABASE_URL" -f init-db/schema.sql
for file in migrations/*.sql; do
  psql "$DATABASE_URL" -f "$file"
done
```

For an existing database, apply only migrations that have not already been applied. Migrations are plain SQL files and must be tracked operationally by the operator.

### 5. Complete OAuth setup

Withings:

```bash
pete withings-auth
pete withings-code "PASTE_CODE_FROM_REDIRECT"
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

Run tests:

```bash
pytest
pytest tests/domain -q
pytest tests/application -q
pytest tests/integration -q
```

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

The repository includes deploy scripts in `pete_e/resources/deploy-wrapper.sh` and `pete_e/resources/deploy.sh`. Their production defaults target `/opt/myapp`; override `PROJECT_ROOT`, `APP_ROOT`, `SHARED_ROOT`, `ENV_FILE`, and `VENV_ROOT` for a different Ubuntu layout.

### Application service

Example `systemd` unit:

```ini
[Unit]
Description=Pete-Eebot API
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=/opt/myapp/current
EnvironmentFile=/opt/myapp/shared/.env
ExecStart=/opt/myapp/shared/venv/bin/uvicorn pete_e.api:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Install and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now peteeebot.service
sudo systemctl status peteeebot.service
```

Do not bind Uvicorn to a public interface in production. Public access should go through nginx.

### Browser console owner

If the browser console is enabled, create the first owner account from the host shell after applying the auth migrations:

```bash
cd /opt/myapp/current
set -a
. /opt/myapp/shared/.env
set +a
psql "$DATABASE_URL" -f migrations/20260515_add_auth_users_sessions_rbac.sql
psql "$DATABASE_URL" -f migrations/20260516_add_auth_mfa_fields.sql
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
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
```

Use route-specific longer timeouts only for trusted command endpoints that intentionally run long operations.

### GitHub deploy flow

The active webhook deploy chain is:

1. GitHub sends `POST /webhook` with `X-Hub-Signature-256`.
2. Pete-Eebot validates `GITHUB_WEBHOOK_SECRET`.
3. The API launches `DEPLOY_SCRIPT_PATH`.
4. The stable wrapper updates the Git checkout.
5. The tracked deploy script installs the package, refreshes cron, sends a Telegram notification, and restarts `peteeebot.service`.

Required deploy environment:

```bash
export GITHUB_WEBHOOK_SECRET="replace-with-shared-webhook-secret"
export DEPLOY_SCRIPT_PATH="/opt/myapp/scripts/deploy.sh"
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
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` | Database connection settings. |
| `DATABASE_URL` | Optional explicit connection string; normally built from `POSTGRES_*`. |
| `DB_HOST_OVERRIDE` | Optional host override used when constructing the connection string. |

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
| `GITHUB_WEBHOOK_SECRET`, `DEPLOY_SCRIPT_PATH`, `PETEEEBOT_CLI_BIN` | GitHub webhook deploy configuration and absolute `pete` CLI path for subprocess jobs. |

### Logging, alerting, and monitoring

| Variable | Purpose |
| --- | --- |
| `PETE_LOG_LEVEL`, `PETE_LOG_FORMAT`, `PETE_LOG_TO_CONSOLE` | Application logging controls. |
| `PETEEEBOT_ALERT_TELEGRAM_ENABLED`, `PETEEEBOT_ALERT_DEDUPE_SECONDS` | Alert delivery controls. |
| `PETEEEBOT_STALE_INGEST_ALERT_DAYS`, `PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD` | Data freshness and failure thresholds. |
| `APPLE_MAX_STALE_DAYS` | Apple ingest stale-data threshold. |
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
- Configure log rotation for `/var/log/pete_eebot`.
- Keep `PETEEEBOT_API_KEY`, `GITHUB_WEBHOOK_SECRET`, Telegram credentials, Dropbox credentials, Withings credentials, and backup encryption keys in a password manager.
- Rotate API and webhook secrets after suspected exposure or client changes.
- Complete `docs/production_readiness_checklist.md` before exposing the service to the internet.

## Historical Deployment

Earlier Raspberry Pi production operation kept secrets, the virtualenv, deploy scripts, and the checkout under a home-directory tree. The supported production baseline is now the `/opt/myapp` layout above; production scripts and cron entries should not depend on a home-directory checkout or an in-repo virtualenv.

## Developer Notes

Useful docs:

- `docs/operator_guide.md`
- `docs/runtime_deploy_runbook.md`
- `docs/logging_observability.md`
- `docs/api_endpoint_inventory.md`
- `docs/production_readiness_checklist.md`
- `docs/planner_feature_flags.md`
- `docs/unified_global_planner.md`
- `docs/pete_coach_openapi.yaml`
- `CONTRIBUTING.md`

Contribution workflow:

1. Create a feature branch.
2. Add or update tests for behavior changes.
3. Run `pytest` and relevant targeted checks.
4. Document operational impact in the PR, including new environment variables, migrations, scheduling changes, or deployment changes.

## Disclaimer

Pete-Eebot provides informational coaching assistance and automation. It is not a medical device and should not replace qualified medical advice.
