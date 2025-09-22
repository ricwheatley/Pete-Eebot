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

## Deployment Paths

Two lightweight options are available for running Pete Eebot:

1. **Python virtual environment (recommended).** Follows the Raspberry Pi-friendly guide in [`docs/venv_setup.md`](docs/venv_setup.md) using the pinned [`requirements.txt`](requirements.txt). This keeps memory usage low and avoids cross-architecture Docker images.
2. **Existing Docker tooling.** The legacy `Dockerfile` targets x86_64 hosts and pairs with `docker-compose.yml` for Postgres only. Use this path when you already operate containerised workloads on a non-ARM server.

The remainder of this README assumes you chose the virtual environment path.

---

## Configuration

1. Copy `.env.sample` to `.env` and populate the secrets.
2. Provide Dropbox credentials (`DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`) and the folder paths produced by Health Auto Export (`DROPBOX_HEALTH_METRICS_DIR`, `DROPBOX_WORKOUTS_DIR`).
3. Fill in the remaining Withings, Telegram, wger, and Postgres values. The configuration module will construct `DATABASE_URL` automatically on load.
   *Legacy note:* older revisions referenced a `GH_SECRETS_TOKEN`; the GitHub integration has been removed so the variable can be dropped from existing `.env` files.
4. Optional reliability tuning: set `APPLE_MAX_STALE_DAYS` (default `3`) to adjust the Dropbox stagnation alert window, and toggle `WITHINGS_ALERT_REAUTH` (default `true`) if you want to silence token re-authorisation nudges.
5. Install the pinned dependencies with `python -m pip install -r requirements.txt`, then register the CLI with `python -m pip install --no-deps -e .`. Both commands should run inside your activated virtual environment.

### First-time OAuth setup

Run these steps once when you provision a new deployment or rotate credentials:

**Withings**

1. Generate an authorisation URL with `pete-e withings-auth-url`.
2. Open the printed link in a browser, approve the `Pete Eebot` app, and copy the `code=...` value from the redirect URL.
3. Exchange the code for tokens: `pete-e withings-exchange-code <code>`.
4. Confirm persistence by running `pete-e refresh-withings`, which refreshes the access token and saves the results to `.withings_tokens.json`.
   The helper locks the file down to owner-only permissions (`chmod 600`) so the stored tokens stay private.

**Dropbox**

1. Visit the [Dropbox App Console](https://www.dropbox.com/developers/apps) and create a **Scoped App** with at least `files.metadata.read` and `files.content.read` permissions.
2. Generate the app key and secret, then use the "Generate" button in the console to obtain a long-lived refresh token for the same app.
3. Add `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, and `DROPBOX_REFRESH_TOKEN` to your `.env` file alongside the export directory paths.

**Sanity check**

`python -m scripts.check_auth` prints a short summary showing whether Withings and Dropbox tokens are in place or highlights the next steps to finish setup. The script works offline, so you can run it before enabling network access on a new host.

The settings layer exposes derived paths such as `logs/pete_history.log`. When running locally the log directory is created automatically.

---

## CLI Usage

The project ships a Typer application under the `pete-e` entry point. Common commands:

* `pete-e refresh-withings` â€“ force-refreshes the Withings OAuth tokens and prints the truncated values.
* `pete-e ingest-apple` â€“ downloads new Health Auto Export files from Dropbox and persists the parsed metrics.
* `pete-e sync --days 7` â€“ runs the multi-source sync (Dropbox, Withings, wger) with retry handling.
* `pete-e withings-sync` â€“ executes the Withings-only branch of the pipeline.
* `pete-e status` - prints a three-line health check for Postgres, Dropbox, and Withings, exiting non-zero on the first failure (use `--timeout` to adjust the 3s per dependency cap).
* `pete-e plan --weeks 4` â€“ generates and deploys the next training plan block (only 4-week plans are supported).
* `pete-e message --summary` / `--plan` â€“ renders summaries and optionally pushes them to Telegram with `--send`.

### Scheduled Messaging

Add the proactive messages to cron (or your scheduler of choice) so the summaries arrive without manual intervention:

```
5 7 * * * pete-e sync --days 1 && pete-e message --summary --send
0 8 * * 1 pete-e message --plan --send
```

The daily path chains a sync before messaging and respects the dispatch ledger, so repeated runs in the same morning will no-op instead of double-sending. If the orchestrator automations are also sending summaries, keep just one of them active to avoid dupe suppression. The weekly plan command now renders the upcoming week header, the key workouts per day, and a closing tip before handing it to Telegram.



### Cron on Raspberry Pi

When you deploy on a Raspberry Pi the CLI is installed as `pete-e`, so you can drop a ready-made cron file into `/etc/cron.d/pete-eebot` (or use `crontab -e`). The example below assumes the project lives at `/home/pi/Pete-Eebot`, the CLI binary is available at `/home/pi/.local/bin/pete-e`, and `python3` resolves to the interpreter you used during setup. Cron executes according to the Pi's system timezone – double-check `timedatectl` if you need to adjust the scheduled hours.

```
SHELL=/bin/bash
PATH=/home/pi/.local/bin:/usr/local/bin:/usr/bin:/bin
MAILTO=""

@reboot   sleep 120 && cd /home/pi/Pete-Eebot && /home/pi/.local/bin/pete-e sync --days 3 --retries 3 >> logs/cron.log 2>&1
5 7 * * *  cd /home/pi/Pete-Eebot && /home/pi/.local/bin/pete-e sync --days 1 --retries 3 && /home/pi/.local/bin/pete-e message --summary --send >> logs/cron.log 2>&1
0 8 * * 1  cd /home/pi/Pete-Eebot && python3 -m scripts.weekly_calibration >> logs/cron.log 2>&1
5 8 * * 1  cd /home/pi/Pete-Eebot && /home/pi/.local/bin/pete-e message --plan --send >> logs/cron.log 2>&1
* * * * *  cd /home/pi/Pete-Eebot && /home/pi/.local/bin/pete-e telegram --listen-once --limit 5 --timeout 25 >> logs/cron.log 2>&1
```

The `@reboot` entry performs a small catch-up sync after power cycles, the daily job runs the full ingest-plus-summary flow, Monday's calibration slot triggers `python3 -m scripts.weekly_calibration` before sharing the refreshed weekly plan, and the minute listener keeps Telegram commands responsive without running a long-lived daemon. Feel free to tweak the hours/minutes once you confirm the Pi timezone is aligned with your expectation.

An optional helper script ships in `scripts/install_cron_examples.sh` to emit the same schedule with override hooks. For example:

```
./scripts/install_cron_examples.sh | sudo tee /etc/cron.d/pete-eebot
```

Override `PETE_BIN`, `PYTHON_BIN`, or `PROJECT_DIR` when your paths differ. Ensure the repo contains a writable `logs/` directory so the cron jobs can append to `logs/cron.log`.


Example:

```
$ pete-e status
DB       OK   9ms
Dropbox  OK   demo@account
Withings OK   scale reachable
```

Logs for each command are appended to `logs/pete_history.log` (or `/var/log/pete_eebot/pete_history.log` when available). The file rotates automatically once it reaches roughly 5 MB, retaining seven backups so long-lived sync services do not accumulate unbounded logs. Each sync command writes a single summary line with per-source statuses, making `tail -n 5 logs/pete_history.log` a quick health check after a run.

### Operations posture

Pete Eebot is maintained on a resource-constrained Raspberry Pi, so the default stance is to keep operations boring and observable:

* **Favour short-lived CLI invocations.** Cron should call a single `pete-e ...` command (or a focused helper in `python -m scripts.<name>`) that exits once the task is complete. Avoid background daemons or bespoke schedulers unless the CLI lacks the feature entirely.
* **Keep scripts experimental until proven.** Anything exploratory, data inspection-heavy, or destined for occasional manual runs belongs under `scripts/`. These helpers should have a narrow scope, document their inputs, and tolerate partial configuration so they are safe to run on the Pi.
* **Promote only hardened flows into `pete_e/`.** When a script graduates into routine automation it should be ported into the typed application package with tests and CLI wiring. This keeps production surfaces discoverable while letting experiments evolve quickly.

Contributors adding operational helpers should default to a cron-able command that fails fast and logs clearly. If the need extends beyond a few weeks of trial runs, raise a discussion before moving the logic into the production package so the maintenance burden stays manageable.

---

## Backups

SD cards fail without warning, so keep the database and credentials replicated to sturdier storage (USB SSD, NAS share, or another host). The repository includes `scripts/backup_db.sh` to automate a weekly rotation that remains silent during successful runs and writes a timestamped record to `logs/backup_db.log`.

### Configuration

* Choose a destination owned by the service account (for example, mount an external disk at `/mnt/pete-eebot-backups`) and export it as `BACKUP_ROOT`. The script defaults to `<project>/backups` when the variable is omitted.
* Optional knobs:
  * `RETENTION_WEEKS` (default `8`) controls how many weeks of dumps and secret copies are retained.
  * `LOG_FILE`, `DB_BACKUP_DIR`, and `SECRETS_BACKUP_DIR` override the derived locations when you want the log on the SD card but the artifacts on external storage.
* The helper reads `.env` for the Postgres connection values and copies both `.env` and `.withings_tokens.json` into the secrets directory. Missing files are skipped with a warning so the backup continues.

The script enforces `umask 077` and normalises directory permissions to `700`, with individual dump and secret copies restricted to `600`. Any existing `latest.dump` or `.env.latest` symlink is updated after each run for quick restores.

### Scheduling

Add the job to cron once the destination is available:

```
0 2 * * 0 BACKUP_ROOT=/mnt/pete-eebot-backups /home/pi/Pete-Eebot/scripts/backup_db.sh >> /home/pi/Pete-Eebot/logs/cron.log 2>&1
```

By default the routine writes its own audit trail to `logs/backup_db.log`. When cron redirects stdout/stderr (as shown above) you also get a one-line summary in the shared `cron.log` file.

### Restoring

1. Pick a dump from the backup location (for example, `postgres/pete_eebot_20240107T020000Z.dump`) and restore it with `pg_restore --clean --if-exists --dbname pete_eebot postgres/pete_eebot_20240107T020000Z.dump`.
2. Copy the desired `.env.TIMESTAMP` and `.withings_tokens.json.TIMESTAMP` back into the project root and drop the `.TIMESTAMP` suffix once you verify the contents.
3. Restart any long-running jobs or services so they pick up the refreshed credentials.

All restore commands should be executed on a trusted machine because the artifacts contain live secrets.

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


