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
./scripts/install_cron_examples.sh --activate --summary
```

---

## Reliability and Recovery

- **Apple sync stagnation detection** alerts when no fresh Apple exports are processed for the configured stale window.
- **Withings reauth guidance** surfaces token refresh failures and points to reauthorization flow.
- **Structured log rotation** prevents unbounded local log growth.
- **Backup helper** (`scripts/backup_db.sh`) supports weekly dumps and secret copy rotation.

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
