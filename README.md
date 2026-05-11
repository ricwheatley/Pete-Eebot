# Pete-Eebot

> A production-minded personal fitness coach that turns health data into actionable training plans, daily readiness insights, and Telegram updates.

Pete-Eebot is a Python application that syncs Apple Health exports (via Dropbox), Withings measurements, and wger workouts into Postgres, then generates coaching outputs (summaries, nudges, and plan messages) through a CLI-first workflow.

---

## Why Pete-Eebot

Most fitness tooling answers *"what happened?"* Pete-Eebot focuses on *"what should I do next?"* 

- **Unifies fragmented data** from Withings, Apple Health, and wger.
- **Automates daily + weekly coaching routines** for consistency.
- **Stays operations-friendly** for Raspberry Pi and other low-resource hosts.
- **Ships with extensive tests** across domain logic, application workflows, and integrations.

---

## Core Capabilities

- **End-to-end daily sync** with source-level status tracking.
- **Dropbox incremental ingestion** for Apple Health Auto Export files.
- **Withings OAuth token lifecycle** (initial auth, refresh, secure persistence).
- **Weekly plan generation** with progression and validation workflows.
- **Telegram delivery** for summaries, plan messages, and proactive nudges.
- **Operational safety rails** like stale-data alerts and auth recovery signals.

---

## Architecture at a Glance

Pete-Eebot uses a layered design:

- `pete_e/domain`: business rules, entities, progression, validation, narrative logic.
- `pete_e/application`: orchestrators and use-case services.
- `pete_e/infrastructure`: clients (Dropbox/Withings/wger/Telegram), DAL, adapters.
- `pete_e/cli`: Typer command entrypoints.
- `migrations` + `init-db`: schema and migration SQL.
- `tests`: broad unit/integration/application coverage.

This separation keeps policy in the domain layer while isolating external dependencies in infrastructure.

---

## Repository Map

```text
.
├── pete_e/                  # Main package (domain, application, infra, CLI)
├── migrations/              # SQL migrations for evolving schema
├── init-db/                 # Base schema bootstrap
├── scripts/                 # Operational and maintenance helpers
├── tests/                   # Test suite (unit + integration + application)
├── docs/                    # API docs, setup notes, deep dives
├── requirements.txt         # Runtime dependency pins
├── pyproject.toml           # Project metadata / packaging
├── docker-compose.yml       # Local Postgres development service
└── README.md
```

---

## Quickstart (Recommended: Python venv)

### 1) Prerequisites

- Python 3.11+
- Postgres 14+
- Dropbox app credentials (for Apple exports)
- Withings API app credentials
- Telegram bot token + chat ID (optional, for messaging)
- wger API key (optional, recommended for richer plan context)

### 2) Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

### 3) Configure environment

Create `.env` in repo root and populate required values:

- Postgres (`POSTGRES_*` or equivalent values used by config)
- Dropbox (`DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`, export directories)
- Withings (`WITHINGS_CLIENT_ID`, `WITHINGS_CLIENT_SECRET`, callback/redirect values)
- Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) if messaging is enabled
- wger (`WGER_API_KEY`) if workout import is enabled

### 4) Bootstrap database

Use your preferred SQL workflow against `init-db/schema.sql`, then apply files in `migrations/`.

### 5) Verify setup

```bash
python -m scripts.check_auth
pete status
```

---

## First-Time OAuth Setup

### Withings

```bash
pete withings-auth
# open URL, approve app, capture `code` from redirect
pete withings-code <code>
pete refresh-withings
```

Tokens are stored in the user config directory and tightened to owner-only permissions.

### Dropbox

1. Create a Scoped App in Dropbox App Console.
2. Grant read scopes needed for metrics/workout exports.
3. Generate refresh token.
4. Add key/secret/refresh token to `.env`.

---

## Daily and Weekly Operations

### Common CLI commands

```bash
pete sync --days 1                 # full multi-source sync
pete ingest-apple                  # Dropbox Apple export ingest only
pete withings-sync                 # Withings branch only
pete message --summary --send      # deliver daily summary
pete message --plan --send         # deliver weekly plan narrative
pete telegram --listen-once        # poll bot commands one time
```

### Example cron jobs

```cron
5 7 * * *  cd /home/pi/Pete-Eebot && pete sync --days 1 --retries 3 && pete message --summary --send >> logs/cron.log 2>&1
25 16 * * 0  cd /home/pi/Pete-Eebot && python3 -m scripts.run_sunday_review >> logs/cron.log 2>&1
30 20 * * 0  cd /home/pi/Pete-Eebot && pete message --plan --send >> logs/cron.log 2>&1
* * * * *  cd /home/pi/Pete-Eebot && pete telegram --listen-once --limit 5 --timeout 25 >> logs/cron.log 2>&1
```

For managed cron installation from repository templates, use:

```bash
./scripts/install_cron_examples.sh --write --activate --summary
```

---

## Raspberry Pi Deployment Layout

The production Pi keeps mutable runtime files outside the Git checkout:

```text
/home/ricwheatley/pete-eebot/.env       # local secrets, not managed by Git
/home/ricwheatley/pete-eebot/venv       # Python virtual environment
/home/ricwheatley/pete-eebot/deploy.sh  # stable webhook entrypoint
/home/ricwheatley/pete-eebot/app        # Git checkout updated from origin/main
```

The root `deploy.sh` should stay small and stable: it pulls `/app` from GitHub, then hands off to the tracked deployment script in `app/pete_e/resources/deploy.sh`. That keeps `.env` and the virtual environment outside the update boundary while still allowing cron updates, package installation, service restart, and Telegram deploy confirmation to come from versioned code.

---

## Backup and Restore

The weekly backup job writes local artifacts outside the Git checkout:

```text
/home/ricwheatley/pete-eebot/backups/postgres/latest.dump
/home/ricwheatley/pete-eebot/backups/secrets/.env.latest
/home/ricwheatley/pete-eebot/backups/secrets/.withings_tokens.json.latest
```

That keeps backups away from `git clean -fdx` during deploys. Optional Dropbox upload can be enabled with:

```bash
BACKUP_CLOUD_UPLOAD=1
DROPBOX_BACKUP_DIR=/Pete-Eebot Backups
BACKUP_ENCRYPTION_KEY_FILE=/home/ricwheatley/pete-eebot/.backup_key
```

The Dropbox app must have write permission for backup upload. Cloud artifacts are encrypted with OpenSSL before upload; keep the key file or passphrase in a password manager because it is required for restore.

Decrypt a cloud backup before restore with the same key file:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in postgres_latest.enc \
  -out latest.dump \
  -pass file:/path/to/backup-key
```

To restore onto a fresh Pi, clone the repo back into `/home/ricwheatley/pete-eebot/app`, restore `.env` and the Withings token file from backup, then restore Postgres:

```bash
cd /home/ricwheatley/pete-eebot/app
set -a; . /home/ricwheatley/pete-eebot/.env; set +a
export PGPASSWORD="$POSTGRES_PASSWORD"
pg_restore -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" --clean --if-exists --no-owner \
  /home/ricwheatley/pete-eebot/backups/postgres/latest.dump
```

---

## Reliability and Recovery

- **Apple sync stagnation detection** alerts when no fresh Apple exports are processed for the configured stale window.
- **Withings reauth guidance** surfaces token refresh failures and points to reauthorization flow.
- **Structured log rotation** prevents unbounded local log growth.
- **Backup helper** (`scripts/backup_db.sh`) supports weekly local dumps, secret copy rotation, and encrypted Dropbox upload.
- **Heartbeat recovery** checks the systemd service every five minutes, restarts it when needed, logs the event, and sends Telegram alerts.

---

## Testing

Run all tests:

```bash
pytest
```

Run targeted suites when iterating:

```bash
pytest tests/domain -q
pytest tests/application -q
pytest tests/integration -q
```

---

## API and Developer Docs

- OpenAPI: `docs/pete_coach_openapi.yaml`
- wger API spec copy: `docs/wger_openapi.yaml`
- Operator guide: `docs/operator_guide.md`
- Body age notes: `docs/body_age.md`
- Contributor guide: `CONTRIBUTING.md`

---

## Design Principles

Pete-Eebot intentionally optimizes for:

1. **Deterministic, scriptable operations** over opaque background processes.
2. **Small-host reliability** (especially Raspberry Pi deployments).
3. **Separation of policy and IO** through layered architecture.
4. **Test-backed iteration** so coaching logic can evolve safely.

---

## Contributing

1. Create a feature branch.
2. Add/update tests with behavior changes.
3. Run `pytest` and relevant targeted checks.
4. Open a PR with operational impact notes (env vars, migrations, scheduling changes).

---

## Disclaimer

Pete-Eebot provides informational coaching assistance and automation. It is **not** a medical device and should not replace qualified medical advice.
