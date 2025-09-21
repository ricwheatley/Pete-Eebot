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
â”œâ”€â”€ pete_e/                 # Python package containing the active application code
â”‚   â”œâ”€â”€ application/        # Orchestration flows (sync, Dropbox ingest, plan generation)
â”‚   â”œâ”€â”€ cli/                # Typer-powered command line interface
â”‚   â”œâ”€â”€ config/             # Environment-driven settings
â”‚   â”œâ”€â”€ domain/             # Business rules (progression, plans, narratives, analytics)
â”‚   â”œâ”€â”€ infrastructure/     # DAL, API clients, and integrations
â”‚   â””â”€â”€ resources/          # Static assets used by the application
â”œâ”€â”€ scripts/                # One-off helpers for maintenance and reviews
â”œâ”€â”€ tests/                  # Pytest suite for ingestion, orchestration, and validation logic
â”œâ”€â”€ docs/                   # Design notes and analytical documentation
â”œâ”€â”€ deprecated/             # Legacy FastAPI/Tailscale implementation retained for reference
â”œâ”€â”€ docker-compose.yml      # Local Postgres bootstrap for development
â””â”€â”€ init-db/                # SQL migrations used by the active schema
```

---

## Configuration

1. Copy `.env.sample` to `.env` and populate the secrets.
2. Provide Dropbox credentials (`DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`) and the folder paths produced by Health Auto Export (`DROPBOX_HEALTH_METRICS_DIR`, `DROPBOX_WORKOUTS_DIR`).
3. Fill in the remaining Withings, Telegram, wger, and Postgres values. The configuration module will construct `DATABASE_URL` automatically on load.
4. Optional reliability tuning: set `APPLE_MAX_STALE_DAYS` (default `3`) to adjust the Dropbox stagnation alert window, and toggle `WITHINGS_ALERT_REAUTH` (default `true`) if you want to silence token re-authorisation nudges.
5. Run `pip install .[dev]` (or use your preferred virtual environment manager) to install the package and its development dependencies.

The settings layer exposes derived paths such as `logs/pete_history.log`. When running locally the log directory is created automatically.

---

## CLI Usage

The project ships a Typer application under the `pete-e` entry point. Common commands:

* `pete-e refresh-withings` â€“ force-refreshes the Withings OAuth tokens and prints the truncated values.
* `pete-e ingest-apple` â€“ downloads new Health Auto Export files from Dropbox and persists the parsed metrics.
* `pete-e sync --days 7` â€“ runs the multi-source sync (Dropbox, Withings, wger) with retry handling.
* `pete-e withings-sync` â€“ executes the Withings-only branch of the pipeline.
* `pete-e status` - prints a three-line health check for Postgres, Dropbox, and Withings, exiting non-zero on the first failure (use `--timeout` to adjust the 3s per dependency cap).
* `pete-e plan --weeks 4` â€“ generates and deploys the next training plan block.
* `pete-e message --summary` / `--plan` â€“ renders summaries and optionally pushes them to Telegram with `--send`.


Example:

```
$ pete-e status
DB       OK   9ms
Dropbox  OK   demo@account
Withings OK   scale reachable
```

Logs for each command are appended to `logs/pete_history.log` (or `/var/log/pete_eebot/pete_history.log` when available). The file rotates automatically once it reaches roughly 5 MB, retaining seven backups so long-lived sync services do not accumulate unbounded logs. Each sync command writes a single summary line with per-source statuses, making `tail -n 5 logs/pete_history.log` a quick health check after a run.

---

## End-to-End Automation Flows

* `run_end_to_end_day(days=1, summary_date=None)` - executes the multi-source daily ingest via the orchestrator and ensures the previous day's Telegram summary is dispatched exactly once. The helper returns a `DailyAutomationResult` with per-source statuses and whether a summary was attempted, making it safe for cron jobs and CLI wrappers to inspect outcomes without reimplementing business logic.
* `run_end_to_end_week(reference_date=None, force_rollover=False, rollover_weeks=4)` - recalibrates the upcoming training week and, when the cadence predicate passes (default: every 4th Sunday), triggers the cycle rollover/export pipeline. The behaviour can be tuned with `AUTO_CYCLE_ROLLOVER_ENABLED` and `CYCLE_ROLLOVER_INTERVAL_WEEKS`, and `force_rollover` provides an explicit override for maintenance scripts. The returned `WeeklyAutomationResult` includes both the calibration summary and any rollover attempt.

These entry points allow CLI commands, Airflow jobs, or simple cron tasks to call a single orchestrator method instead of chaining bespoke scripts.

---

## Reliability Checks & Recovery

- **Apple Dropbox stagnation:** The orchestrator logs and sends a Telegram alert when no new Apple Health exports have been processed for the configured `APPLE_MAX_STALE_DAYS` window (default three days). Increase the value if weekend gaps are expected.
- **Withings token recovery:** If the Withings refresh token is rejected, the sync flags the source as failed and emits an alert (unless `WITHINGS_ALERT_REAUTH` is `false`). Re-authorise by running `pete-e withings-auth-url`, approving the app in the browser, then calling `pete-e withings-exchange-code <code>` followed by `pete-e refresh-withings` to confirm the new tokens are persisted.

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


