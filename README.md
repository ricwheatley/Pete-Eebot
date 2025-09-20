# Pete Eebot

Pete-Eebot is a personal health and fitness orchestrator. The application ingests data from connected services, persists it in Postgres, analyses daily readiness, and prepares weekly training plans and summaries that can be reviewed or pushed to Telegram.

---

## Key Features

* **Unified data sync:** A single CLI command keeps Withings, Apple Health, and wger data aligned in the database.
* **Dropbox-based Apple ingest:** Health Auto Export shortcuts drop JSON/ZIP files into Dropbox; the ingest job downloads and loads only the new files each run.
* **Body age insights:** Daily body age scores highlight long-term trends across movement, recovery, and composition data.
* **Training plan automation:** Plan blocks are generated directly from the data warehouse and can be shared via the messenger commands.

---

## Data Sources and Integrations

* **Withings:** OAuth credentials are stored locally. The sync pipeline refreshes tokens as needed and pulls weight and body composition summaries for the requested backfill window.
* **Apple Health:** An iOS Shortcut exports Health Auto Export files to Dropbox. The Dropbox client collects any new metric or workout files, parses them, and writes them into the analytics schema.
* **wger:** Strength training logs are fetched through the wger API and blended with health metrics for the weekly plan narrative.

---

## Repository Layout

```
.
├── pete_e/                 # Python package containing the active application code
│   ├── application/        # Orchestration flows (sync, Dropbox ingest, plan generation)
│   ├── cli/                # Typer-powered command line interface
│   ├── config/             # Environment-driven settings
│   ├── domain/             # Business rules (progression, plans, narratives, analytics)
│   ├── infrastructure/     # DAL, API clients, and integrations
│   └── resources/          # Static assets used by the application
├── scripts/                # One-off helpers for maintenance and reviews
├── tests/                  # Pytest suite for ingestion, orchestration, and validation logic
├── docs/                   # Design notes and analytical documentation
├── deprecated/             # Legacy FastAPI/Tailscale implementation retained for reference
├── docker-compose.yml      # Local Postgres bootstrap for development
└── init-db/                # SQL migrations used by the active schema
```

---

## Configuration

1. Copy `.env.sample` to `.env` and populate the secrets.
2. Provide Dropbox credentials (`DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`) and the folder paths produced by Health Auto Export (`DROPBOX_HEALTH_METRICS_DIR`, `DROPBOX_WORKOUTS_DIR`).
3. Fill in the remaining Withings, Telegram, wger, and Postgres values. The configuration module will construct `DATABASE_URL` automatically on load.
4. Run `pip install .[dev]` (or use your preferred virtual environment manager) to install the package and its development dependencies.

The settings layer exposes derived paths such as `logs/pete_history.log`. When running locally the log directory is created automatically.

---

## CLI Usage

The project ships a Typer application under the `pete-e` entry point. Common commands:

* `pete-e refresh-withings` – force-refreshes the Withings OAuth tokens and prints the truncated values.
* `pete-e ingest-apple` – downloads new Health Auto Export files from Dropbox and persists the parsed metrics.
* `pete-e sync --days 7` – runs the multi-source sync (Dropbox, Withings, wger) with retry handling.
* `pete-e withings-sync` – executes the Withings-only branch of the pipeline.
* `pete-e plan --weeks 4` – generates and deploys the next training plan block.
* `pete-e message --summary` / `--plan` – renders summaries and optionally pushes them to Telegram with `--send`.

Logs for each command are appended to `logs/pete_history.log`, making it easy to audit Dropbox downloads and downstream calculations.

---

## Testing

Run the automated test suite with:

```
pytest
```

The tests provide in-memory doubles for the DAL and Dropbox client, ensuring the new module structure and ingestion format remain stable.

---

## Legacy Code

The `deprecated/` directory contains the retired FastAPI webhook and the original Tailscale-based Apple ingestion flow. It is kept for historical reference only; new development should rely on the active package in `pete_e/`.
