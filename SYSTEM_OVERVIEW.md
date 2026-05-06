# Pete-Eebot System Overview

Generated as a repository-level documentation and governance review.

Source basis: GitHub repository `ricwheatley/Pete-Eebot`, default branch `main`, observed around commit `b516ec0c74f06a56a3e5a6ebaa50e7901ce9d2b9` via repository search and selected source-file reads.

> Scope note: this document is a structured first-pass inventory and architecture review. It is based on the modules surfaced by GitHub code search plus direct reads of key files. It should be followed by an AST-generated pass from a local clone to guarantee that every nested helper, private function, test fixture, and script-level function is captured mechanically.

---

## 1. Project shape

Pete-Eebot is a Python package named `pete_e`. The package is installed with setuptools and exposes a command-line entry point:

```toml
pete = "pete_e.cli.messenger:app"
```

Runtime dependencies include:

- `fastapi`, `uvicorn` for the HTTP API.
- `typer`, `click`, `rich` for CLI commands and console output.
- `psycopg`, `psycopg_pool` for PostgreSQL access.
- `pydantic`, `pydantic-settings` for configuration.
- `requests`, `tenacity` for external API clients and retry behaviour.
- `dropbox` for Apple Health import from Dropbox.
- `Jinja2`, `python-dateutil` for templating/date handling.

Broad responsibilities:

| Layer | Package area | Responsibility |
|---|---|---|
| API | `pete_e/api.py` | FastAPI endpoints, API-key validation, webhook handling, API service wiring. |
| CLI | `pete_e/cli/*` | User-facing commands for sync, plans, status, Telegram and other operational workflows. |
| Application | `pete_e/application/*` | Orchestration services that coordinate DAL, external clients, planning, validation, and messaging. |
| Domain | `pete_e/domain/*` | Business rules, entities, training plan construction, scheduling, progression, readiness, validation and narrative logic. |
| Infrastructure | `pete_e/infrastructure/*` | Database access, external clients, Dropbox/Apple/Withings/Wger integration, Telegram delivery, cron and Git utilities. |
| Utilities | `pete_e/utils/*` | Reusable conversion, formatting, maths, and helper functions. |
| Scripts | `scripts/*` | Operational one-off runners, auth checks, plan generation, calibration and review jobs. |
| Tests/mocks | `tests/*`, `mocks/*` | Behavioural tests and lightweight stand-ins for external dependencies. |

---

## 2. Object inventory — modules and responsibilities

### 2.1 Root/package configuration

#### `pyproject.toml`

Defines build backend, package metadata, runtime dependencies, development dependencies, and CLI entry point.

Key implication: CLI behaviour starts in `pete_e.cli.messenger:app`; API behaviour starts separately in `pete_e.api:app`.

#### `pete_e/config/config.py`

Expected role: central pydantic settings object. Based on usage from `api.py`, settings include at least:

- `PETEEEBOT_API_KEY`
- `GITHUB_WEBHOOK_SECRET`
- `DEPLOY_SCRIPT_PATH`
- `log_path`
- running goal fields such as `RUNNING_TARGET_RACE`, `RUNNING_RACE_DATE`, `RUNNING_TARGET_TIME`, `RUNNING_WEIGHT_LOSS_TARGET_KG`
- `USER_GOAL_WEIGHT_KG`

Main consumers:

- `pete_e.api`
- `pete_e.application.api_services`
- database and client infrastructure modules.

#### `pete_e/config/__init__.py`

Expected role: exports `settings` so modules can import `from pete_e.config import settings`.

---

### 2.2 API module

#### `pete_e/api.py`

FastAPI entry point. Defines global singleton-ish service instances and all public HTTP endpoints.

Module globals:

| Object | Purpose |
|---|---|
| `app` | `FastAPI(title="Pete-Eebot API")`. |
| `_dal` | Lazily-initialised `PostgresDal`. |
| `_metrics_service` | Lazily-initialised `MetricsService`. |
| `_plan_service` | Lazily-initialised `PlanService`. |
| `_status_service` | Lazily-initialised `StatusService`. |

Functions:

| Function | Type | Purpose |
|---|---:|---|
| `_secret_to_str(value)` | helper | Normalises plain strings and pydantic secret values. |
| `_configured_api_key()` | helper | Reads configured API key; raises 503 if missing. |
| `_configured_webhook_secret()` | helper | Reads GitHub webhook secret and returns UTF-8 bytes; raises 503 if missing. |
| `_configured_deploy_script_path()` | helper | Reads, expands and validates deploy script path; raises 503/500 on misconfiguration. |
| `get_dal()` | factory/cache | Lazily creates the shared `PostgresDal`. |
| `get_metrics_service()` | factory/cache | Lazily creates `MetricsService(get_dal())`. |
| `get_plan_service()` | factory/cache | Lazily creates `PlanService(get_dal())`. |
| `get_status_service()` | factory/cache | Lazily creates `StatusService(get_dal())`. |
| `validate_api_key(request, x_api_key)` | auth helper | Accepts API key from `X-API-Key` header or `api_key` query parameter; validates with `hmac.compare_digest`. |
| `root_get()` | `GET /` | Connector validation/basic liveness. |
| `root_post(request)` | `POST /` | POST root liveness. |
| `metrics_overview(...)` | `GET /metrics_overview` | Calls `MetricsService.overview(date)`. |
| `daily_summary(...)` | `GET /daily_summary` | Calls `MetricsService.daily_summary(date)`. |
| `recent_workouts(...)` | `GET /recent_workouts` | Calls `MetricsService.recent_workouts(days, end_date)`. |
| `coach_state(...)` | `GET /coach_state` | Calls `MetricsService.coach_state(date)`. Primary Custom GPT coaching endpoint. |
| `goal_state(...)` | `GET /goal_state` | Calls `MetricsService.goal_state()`. |
| `user_notes(...)` | `GET /user_notes` | Calls `MetricsService.user_notes(days)`. |
| `plan_context(...)` | `GET /plan_context` | Calls `MetricsService.plan_context(date)`. |
| `sse(...)` | `GET /sse` | Streams current server time every five seconds. |
| `plan_for_day(...)` | `GET /plan_for_day` | Calls `PlanService.for_day(date)`. |
| `plan_for_week(...)` | `GET /plan_for_week` | Calls `PlanService.for_week(start_date)`. |
| `status(...)` | `GET /status` | Wraps CLI status checks and returns structured check list plus rendered summary. |
| `sync(...)` | `POST /sync` | Calls `run_sync_with_retries(days, retries)`. |
| `logs(...)` | `GET /logs` | Returns tail of configured history log. |
| `run_pete_plan_async(...)` | `POST /run_pete_plan_async` | Fire-and-forget subprocess: `pete plan --weeks ... --start-date ...`. |
| `github_webhook(request)` | `POST /webhook` | Validates GitHub HMAC SHA-256 signature and runs configured deploy script with `subprocess.Popen`. |

Important design notes:

- API authentication is duplicated in every protected endpoint through `validate_api_key`.
- The API accepts API key via query string as well as header. Query string keys are easier to leak through logs and browser history.
- Subprocess use exists in API request handlers. That is powerful, but needs strict operational governance.

---

### 2.3 Application services

#### `pete_e/application/api_services.py`

Application-facing service layer used by `api.py`.

Module constants:

| Object | Purpose |
|---|---|
| `_METRIC_UNITS` | Maps metric names to display units. |
| `_PRIMARY_FIELDS` | Metrics used for core data quality/completeness. |
| `_LOW_TRUST_FIELDS` | Metrics treated as lower-trust context. |

Module helpers:

| Function | Purpose |
|---|---|
| `_json_safe(value)` | Converts `Decimal`, `date`, `datetime`, dicts and sequences to JSON-safe values. |
| `_avg(values)` | Average helper returning `None` for empty input. |
| `_window_rows(rows, start, end)` | Filters row list to date range. |
| `_numeric_values(rows, field)` | Extracts numeric float values from rows. |
| `_sum_field(rows, field)` | Sums numeric values for a field. |

Classes:

##### `_DateParserMixin`

Shared ISO date parser.

| Method | Purpose |
|---|---|
| `_parse_iso_date(value, field)` | Parses `YYYY-MM-DD`; raises field-specific `ValueError`. |

##### `MetricsService`

Read-only coaching and metrics service. Depends on `PostgresDal`.

| Method | Purpose |
|---|---|
| `__init__(dal)` | Stores DAL. |
| `overview(iso_date)` | Calls DAL `get_metrics_overview`. |
| `daily_summary(iso_date)` | Returns normalised metrics with units/source/trust/data quality metadata. |
| `recent_workouts(days=14, iso_end_date=None)` | Returns running and strength sessions over bounded lookback window. |
| `coach_state(iso_date)` | Builds compact GPT coaching state: readiness, deltas, loads, plan context, goals, quality, subjective-input gaps, coaching notes. |
| `goal_state()` | Returns running/body-composition/strength goals and performance anchors. |
| `user_notes(days=14)` | Currently returns placeholder noting subjective notes are not persisted. |
| `plan_context(iso_date)` | Determines active plan, week number, deload state, phase and next deload week. |
| `_source_for_metric(key)` | Classifies metric source. |
| `_completeness_pct(rows, fields)` | Calculates observed-field completeness. |
| `_run_load(workouts, target_date, days)` | Calculates running distance load for a period. |
| `_coach_data_quality(...)` | Calculates last sync, stale days, completeness and reliability flag. |
| `_possible_underfueling(...)` | Flags rapid weight loss plus adverse recovery signals. |
| `_readiness_state(...)` | Converts recovery/data quality inputs to `green`/`amber`/`red`. |
| `_latest_training_maxes()` | Delegates to DAL if method exists. |
| `_latest_training_max_date()` | Delegates to DAL if method exists. |
| `_next_deload_week(current_week, total_weeks)` | Finds next week divisible by four within plan bounds. |

##### `PlanService`

Read-only plan service.

| Method | Purpose |
|---|---|
| `__init__(dal)` | Stores DAL. |
| `for_day(iso_date)` | Calls DAL stored procedure wrapper `get_plan_for_day`. |
| `for_week(iso_start_date)` | Calls DAL stored procedure wrapper `get_plan_for_week`. |

##### `StatusService`

Thin wrapper around CLI status checks.

| Method | Purpose |
|---|---|
| `__init__(dal)` | Stores DAL, though current method defers to CLI. |
| `run_checks(timeout)` | Imports and calls `pete_e.cli.status.run_status_checks`. |

---

### 2.4 Core orchestration modules

#### `pete_e/application/sync.py`

Expected role: top-level sync runner. Called from API `/sync`, CLI sync command, and cron.

Likely responsibilities:

- Run source-specific syncs for Withings, Apple Health/Dropbox, Wger and derived summaries.
- Apply retry handling through `run_sync_with_retries(days, retries)`.
- Return an object with at least: `success`, `attempts`, `failed_sources`, `source_statuses`, `undelivered_alerts`, `label`, and `summary_line(days)`.

#### `pete_e/application/orchestrator.py`

Expected role: coordinates domain planning/services and infrastructure dependencies. Likely sits behind CLI commands for plan generation, morning reports or review workflows.

#### `pete_e/application/services.py`

Expected role: broader application service facade for non-API flows. Potential overlap with `api_services.py`; this should be reviewed for duplication.

#### `pete_e/application/plan_generation.py`

Expected role: builds training plans using domain plan factory/mapper/scheduler and persists through DAL.

#### `pete_e/application/plan_context_service.py`

Expected role: application wrapper for retrieving/formatting active plan context.

#### `pete_e/application/progression_service.py`

Expected role: evaluates progression/backoff decisions using domain progression rules and DAL history.

#### `pete_e/application/validation_service.py`

Expected role: runs training-plan or data-quality validations using domain validation functions.

#### `pete_e/application/catalog_sync.py`

Expected role: sync Wger exercise/catalog data into local PostgreSQL tables.

#### `pete_e/application/wger_sync.py`

Expected role: sync or reconcile Wger logs/workouts into local storage.

#### `pete_e/application/wger_sender.py`

Expected role: send workouts/logs/macros to Wger or wrapper API.

#### `pete_e/application/apple_dropbox_ingest.py`

Expected role: retrieve Apple Health export files from Dropbox and pass them through parser/writer ingestion flow.

#### `pete_e/application/telegram_listener.py`

Expected role: receive/poll Telegram messages, classify commands and call relevant application behaviours.

#### `pete_e/application/exceptions.py`

Expected role: typed application exceptions.

---

### 2.5 Data access / persistence

#### `pete_e/infrastructure/postgres_dal.py`

Primary PostgreSQL DAL. Implements `PlanRepository` and directly contains plan persistence, data reads/writes, catalog sync writes, health metric persistence and stored procedure wrappers.

Module objects:

| Object | Purpose |
|---|---|
| `_pool` | Shared psycopg connection pool. |
| `_PLAN_GENERATION_LOCK_KEY` | Advisory lock key used to serialize plan generation/export. |
| `_create_pool()` | Builds `ConnectionPool` from configured database URL. |
| `get_pool()` | Lazily creates global pool. |

Class: `PostgresDal(PlanRepository)`

Key methods seen directly:

| Method | Purpose |
|---|---|
| `__init__(pool=None)` | Stores injected or global connection pool. |
| `_get_cursor(use_dict_row=True)` | Context manager yielding cursor with optional dict rows. |
| `connection()` | Exposes pooled connection context manager. |
| `close()` | Closes pool. |
| `_ensure_single_active_plan_invariant(cur)` | Deactivates duplicate active plans and creates partial unique index for active plan. |
| `_core_pool_table_exists(cur)` | Checks whether `public.core_pool` exists. |
| `hold_plan_generation_lock()` | Uses PostgreSQL advisory lock to serialize plan generation. |
| `save_full_plan(plan_dict)` | Validates full plan payload, deactivates prior active plan, inserts plan/weeks/workouts transactionally. |
| `get_assistance_pool_for(main_lift_id)` | Returns assistance exercise IDs for main lift. |
| `get_core_pool_ids()` | Returns core pool IDs from `core_pool` or Wger category fallback. |
| `create_block_and_plan(start_date, weeks=4)` | Creates active plan and week rows. |
| `insert_workout(**kwargs)` | Inserts one training plan workout. |
| `get_active_plan()` | Returns current active plan. |
| `get_plan_week_rows(plan_id, week_number)` | Returns ordered workouts for plan week. |
| `get_plan_week(plan_id, week_number)` | Compatibility wrapper. |
| `get_plan_for_day(target_date)` | Calls stored function `sp_plan_for_day`. |
| `get_plan_for_week(start_date)` | Calls stored function `sp_plan_for_week`. |
| `get_week_ids_for_plan(plan_id)` | Maps week number to week row ID. |
| `find_plan_by_start_date(start_date)` | Finds latest plan with matching start date. |
| `has_any_plan()` | Boolean existence check for training plans. |
| `update_workout_targets(updates)` | Batch-updates workout target weights. |
| `apply_plan_backoff(week_start_date, set_multiplier, rir_increment)` | Reduces sets/increases RIR for a specific week. |
| `create_test_week_plan(start_date)` | Creates active one-week strength-test plan. |
| `get_latest_test_week()` | Returns latest test week metadata. |
| `insert_strength_test_result(**kwargs)` | Upserts strength test result by plan/week/lift. |
| `upsert_training_max(lift_code, tm_kg, measured_at, source)` | Upserts training max. |
| `get_latest_training_maxes()` | Latest training max per lift. |
| `get_latest_training_max_date()` | Latest measured date across training maxes. |
| `save_withings_daily(...)` | Upserts daily Withings metric row. |
| `_epoch_to_timestamp(value)` | Converts epoch to UTC datetime. |
| `save_withings_measure_groups(day, measure_groups)` | Upserts raw Withings measure groups. |
| `save_wger_log(day, exercise_id, set_number, reps, weight_kg, rir)` | Upserts set-level Wger log. |
| `load_lift_log(exercise_ids, start_date=None, end_date=None)` | Reads Wger logs grouped by exercise ID. |
| `_bulk_upsert(table_name, data, conflict_keys, update_keys)` | Generic psycopg SQL-composed bulk upsert. |
| `upsert_wger_exercises_and_relations(exercises)` | Upserts exercises and associated equipment/muscle join tables. |
| `seed_main_lifts_and_assistance(main_lift_ids, assistance_pool_data)` | Marks main lifts and inserts assistance pool rows. |

Additional methods are expected later in the file based on API service usage:

- `_call_function(...)`
- `get_metrics_overview(...)`
- `get_daily_summary(...)`
- `get_historical_data(...)`
- `get_recent_running_workouts(...)`
- `get_recent_strength_workouts(...)`

Governance note: this file is doing many jobs: connection pool, repository implementation, schema constraints, plan persistence, Wger catalog management, Withings writes, metrics reads, and stored procedure access. It is a high-risk god object.

#### `pete_e/infrastructure/db_conn.py`

Expected role: builds PostgreSQL connection URL from settings/environment. Used by `postgres_dal.get_database_url()`.

#### `pete_e/domain/data_access.py`

Expected role: domain interface/protocol for data access. Potentially older abstraction now partly superseded by `repositories.py` and concrete `PostgresDal`.

#### `pete_e/domain/repositories.py`

Defines repository interfaces such as `PlanRepository`; `PostgresDal` implements at least `PlanRepository`.

---

### 2.6 Domain model and planning

#### `pete_e/domain/entities.py`

Expected role: domain entities / dataclasses / pydantic models for workouts, plans, exercises, metrics, logs or summaries.

#### `pete_e/domain/plan_factory.py`

Expected role: constructs training plan structures from schedule rules, progression rules and user context before persistence.

#### `pete_e/domain/plan_mapper.py`

Expected role: maps plan objects between domain representation and persistence/API representation. There is also an infrastructure mapper with the same name, so naming/responsibility should be reviewed.

#### `pete_e/infrastructure/mappers/plan_mapper.py`

Expected role: persistence/external representation mapper for plans. Possible overlap with `domain/plan_mapper.py`.

#### `pete_e/domain/scheduler.py`

Expected role: day/week scheduling logic for strength/running/recovery sessions.

#### `pete_e/domain/schedule_rules.py`

Expected role: constants and rules such as main lift IDs, weekly layout, sequence ordering, slot definitions and exercise pools.

#### `pete_e/domain/progression.py`

Expected role: progression/backoff rules for strength and plan targets.

#### `pete_e/domain/running_planner.py`

Expected role: running session planning — distances, intensities, run types and weekly run structure.

#### `pete_e/domain/cycle_service.py`

Expected role: mesocycle/block rollover and training-cycle logic.

#### `pete_e/domain/lift_log.py`

Expected role: lift log analysis, set/reps/weight aggregation, e1RM or progression support.

#### `pete_e/domain/metrics_service.py`

Expected role: domain-level metric calculations. Possible overlap with `application/api_services.MetricsService`.

#### `pete_e/domain/body_age.py`

Expected role: derives body-age related metrics and summaries.

#### `pete_e/domain/validation.py`

Expected role: domain validation rules. Exported constant seen from DAL: `MAX_BASELINE_WINDOW_DAYS`.

#### `pete_e/domain/configuration.py`

Expected role: domain-level configuration model or config access object.

#### `pete_e/domain/daily_sync.py`

Expected role: daily sync domain summary/status logic, separate from application `sync.py`.

#### `pete_e/domain/logging.py`

Expected role: domain-specific logging or structured log models. Possible naming confusion with standard `logging`.

#### `pete_e/domain/french_trainer.py`

Expected role: persona/text layer for Pete-Eebot’s French/British trainer voice.

#### `pete_e/domain/narrative_builder.py`

Expected role: builds human-readable reports/messages from metrics, plan and readiness data.

#### `pete_e/domain/narrative_utils.py`

Expected role: smaller narrative helpers used by `narrative_builder.py`.

#### `pete_e/domain/phrase_picker.py`

Expected role: phrase selection/variation for messages.

#### `pete_e/domain/user_helpers.py`

Expected role: user-specific helper functions, probably formatting/preference defaults.

#### `pete_e/domain/token_storage.py`

Expected role: domain abstraction for token storage. There is also an infrastructure implementation.

---

### 2.7 External integrations

#### `pete_e/infrastructure/withings_client.py`

Expected role: Withings API client for body measurements and related health data.

#### `pete_e/infrastructure/withings_oauth_helper.py`

Expected role: OAuth helper for Withings token acquisition/refresh.

#### `pete_e/infrastructure/token_storage.py`

Expected role: concrete token persistence for OAuth/client tokens.

#### `pete_e/infrastructure/wger_client.py`

Expected role: Wger API client for exercise catalog, plans/logs and possibly macro/nutrition actions.

#### `pete_e/infrastructure/mappers/wger_mapper.py`

Expected role: maps Wger API resource objects into local database payloads such as exercise, equipment, category and muscle structures.

#### `pete_e/infrastructure/apple_dropbox_client.py`

Expected role: Dropbox client for fetching Apple Health export files.

#### `pete_e/infrastructure/apple_parser.py`

Expected role: parse Apple Health export files into normalised records.

#### `pete_e/infrastructure/apple_writer.py`

Expected role: write parsed Apple Health records to PostgreSQL.

#### `pete_e/infrastructure/apple_health_ingestor.py`

Expected role: end-to-end Apple Health ingestion coordinator.

#### `pete_e/infrastructure/telegram_client.py`

Expected role: Telegram API client.

#### `pete_e/infrastructure/telegram_sender.py`

Expected role: sends Telegram messages/reports/alerts.

#### `pete_e/infrastructure/cron_manager.py`

Expected role: manage or render cron schedules for Pi-hosted operational jobs.

#### `pete_e/infrastructure/git_utils.py`

Expected role: Git metadata helpers, likely used by status/deploy diagnostics.

#### `pete_e/infrastructure/decorators.py`

Expected role: infrastructure decorators, likely for retry/timing/logging/error handling.

#### `pete_e/infrastructure/log_utils.py`

Expected role: common logging functions such as `info()` and `warn()` used by DAL.

---

### 2.8 CLI modules

#### `pete_e/cli/messenger.py`

Main Typer app exposed as `pete` command. Expected to register commands for sync, status, plan generation, morning reports, Telegram, etc.

#### `pete_e/cli/status.py`

Status-check command module. Directly imported by API.

Objects seen from API usage:

| Object | Purpose |
|---|---|
| `DEFAULT_TIMEOUT_SECONDS` | Default dependency check timeout. |
| `render_results(results)` | Converts status check results into display string. |
| `run_status_checks(timeout)` | Executes checks for API/CLI status output. |

#### `pete_e/cli/telegram.py`

Expected role: CLI commands around Telegram listener/sender functionality.

---

### 2.9 Utilities

#### `pete_e/utils/converters.py`

Expected role: robust coercion helpers. Used directly by `api_services` for dates/floats.

Known functions from usage:

| Function | Purpose |
|---|---|
| `to_date(value)` | Convert value to `date` or `None`. |
| `to_float(value)` | Convert value to float or `None`. |

#### `pete_e/utils/formatters.py`

Expected role: reusable display formatting helpers.

#### `pete_e/utils/math.py`

Expected role: numeric helper functions.

#### `pete_e/utils/helpers.py`

Expected role: miscellaneous shared helpers.

#### `pete_e/utils/__init__.py`

Expected role: package export surface for utility modules.

---

### 2.10 Scripts

#### `scripts/check_auth.py`

Operational auth/token checker.

#### `scripts/weekly_calibration.py`

Weekly calibration runner, likely analyses recent data and updates training/rules.

#### `scripts/heartbeat_check.py`

Operational heartbeat/status script.

#### `scripts/run_sunday_review.py`

Sunday review runner.

#### `scripts/generate_plan.py`

Plan generation script entry point.

#### `scripts/inspect_withings_response.py`

Inspection/debug script for Withings API payloads.

---

### 2.11 Tests and mocks

#### `tests/*`

Observed tests cover:

- day-in-life scenarios
- cycle rollover
- sync summary logging
- trend commentary
- body age summary
- sanity checks
- plan service
- plan builder
- readiness alerts
- strength test
- PostgreSQL DAL
- strength week integration

This is good coverage directionally, but the review should check whether the tests assert current behaviour tightly or mainly act as smoke tests.

#### `mocks/*`

Observed mocks:

- `mocks/psycopg_mock/*`
- `mocks/pydantic_mock/*`
- `mocks/pydantic_settings_mock/*`
- `mocks/requests_mock/*`

These appear to support tests without requiring all real third-party packages or live services.

---

## 3. How the parts work together

### 3.1 Public API flow

```text
HTTP client / Custom GPT Action
    -> FastAPI endpoint in pete_e/api.py
        -> validate_api_key()
        -> lazy service factory
            -> MetricsService / PlanService / StatusService
                -> PostgresDal or CLI status function
                    -> PostgreSQL / stored procedures / health checks
        -> JSON response
```

Primary example: `/coach_state`

```text
GET /coach_state?date=YYYY-MM-DD
    -> validate API key
    -> MetricsService.coach_state(date)
        -> DAL.get_historical_data(last 35 days)
        -> recent_workouts(last 14 days)
            -> DAL.get_recent_running_workouts
            -> DAL.get_recent_strength_workouts
        -> plan_context(date)
            -> DAL.get_active_plan
        -> goal_state()
            -> settings + DAL latest training maxes
        -> derived readiness/readiness colour/data-quality flags
    -> compact coaching JSON
```

This is the object ChatGPT/Pete uses for coaching decisions.

### 3.2 Sync flow

```text
cron / CLI / POST /sync
    -> run_sync_with_retries(days, retries)
        -> source-specific sync modules
            -> Withings client -> DAL.save_withings_daily / save_withings_measure_groups
            -> Apple Dropbox client -> parser -> writer/DAL
            -> Wger client -> mapper -> DAL wger tables/logs
        -> summary object
    -> API/CLI/Telegram report/log output
```

The Pi crontab previously discussed runs roughly:

```text
pete sync --days 1 --retries 3
pete morning-report --send
```

So sync completeness directly controls what `/coach_state` can see later.

### 3.3 Plan generation flow

```text
CLI/script/API async trigger
    -> application plan generation/orchestration
        -> domain plan factory/scheduler/progression/running planner
            -> plan dictionary/domain objects
        -> PostgresDal.hold_plan_generation_lock()
        -> PostgresDal.save_full_plan()
            -> deactivate old active plan
            -> insert training_plans
            -> insert training_plan_weeks
            -> insert training_plan_workouts
```

The DAL enforces a single active plan both by update logic and a partial unique index.

### 3.4 Status/ops flow

```text
CLI pete status or GET /status
    -> pete_e.cli.status.run_status_checks(timeout)
        -> database/API/log/dependency checks
    -> render_results(results)
    -> CLI text or API JSON
```

### 3.5 Telegram/narrative flow

```text
scheduled report or listener input
    -> application orchestration
        -> metrics/plan/domain narrative builder
        -> phrase picker / trainer persona
        -> Telegram sender/client
```

The narrative layer appears intentionally separate from raw metric calculation, which is the right direction.

---

## 4. Issues and risks from rapid/vibe-coded evolution

This section distinguishes confirmed issues from risks that should be verified by local test/AST pass.

### 4.1 Confirmed or strongly indicated issues

#### 1. `PostgresDal` is overloaded

`PostgresDal` owns connection pooling, plan persistence, training maxes, Wger logs, Withings writes, Wger catalog upserts, plan backoff, stored procedure wrappers and probably metrics reads.

Risk:

- Hard to test in isolation.
- Changes for one integration can break another.
- Transaction boundaries become harder to reason about.
- Repository interfaces become ceremonial if the concrete class grows without bounds.

Recommended direction:

- Split into focused repositories/services:
  - `PlanRepository`
  - `MetricsRepository`
  - `WithingsRepository`
  - `WgerRepository`
  - `CatalogRepository`
  - `TrainingMaxRepository`
- Keep `PostgresDal` temporarily as a facade while callers are migrated.

#### 2. Multiple layers appear to duplicate concepts

Examples:

- `domain/plan_mapper.py` and `infrastructure/mappers/plan_mapper.py`
- `domain/token_storage.py` and `infrastructure/token_storage.py`
- `domain/metrics_service.py` and `application/api_services.MetricsService`
- `application/services.py` and `application/api_services.py`
- `application/sync.py` and `domain/daily_sync.py`

Risk:

- Confused ownership.
- Duplicate behaviour diverges silently.
- New features may be added to the wrong layer.

Recommended direction:

- Define layer rules:
  - Domain: pure business rules and models. No DB, HTTP, files, environment, subprocess.
  - Application: use-case orchestration.
  - Infrastructure: side effects, APIs, persistence.
  - API/CLI: adapters only.
- Rename or consolidate duplicated modules once responsibility is explicit.

#### 3. API key accepted in query string

`validate_api_key` accepts `X-API-Key` header or `?api_key=` query parameter.

Risk:

- Query strings commonly appear in reverse proxy logs, browser history, monitoring, referrers and error traces.

Recommended direction:

- Keep query string temporarily only if Custom GPT/action constraints require it.
- Prefer header-only authentication.
- If query support remains, explicitly redact query strings in logs and document it as a compatibility exception.

#### 4. API endpoints spawn subprocesses

`/run_pete_plan_async` spawns `pete plan ...`; `/webhook` spawns deploy script.

Risk:

- Fire-and-forget means no structured completion status.
- Process failures may be invisible unless logs are perfect.
- Running deploy from web process increases blast radius.

Recommended direction:

- Move background jobs to a queue/worker or systemd-run wrapper.
- Record job ID, start time, command, status and log path.
- Restrict webhook by GitHub event type/ref, not only HMAC.

#### 5. Singleton globals in API

`api.py` caches DAL/services in module-level globals.

Risk:

- Harder lifecycle control.
- Test contamination.
- Awkward for multi-worker deployment and graceful shutdown.

Recommended direction:

- Use FastAPI dependencies/lifespan events.
- Initialise/close connection pools explicitly.

#### 6. Business thresholds are embedded in service code

Examples from `MetricsService`:

- sleep target hard-coded at 420 minutes.
- sleep debt thresholds 120/210 minutes.
- RHR/HRV deltas hard-coded.
- deload every 4 weeks.
- performance anchors hard-coded.

Risk:

- Hard to tune without code changes.
- Assumptions become invisible.
- Coaching behaviour changes require redeploys.

Recommended direction:

- Move thresholds into versioned config or database tables.
- Document clinical/training rationale for each threshold.

#### 7. Placeholder subjective inputs

`user_notes()` returns `not_configured`; `coach_state()` always lists subjective fields as missing.

Risk:

- Coach output can look richer than its input quality supports.
- Readiness decisions may over-weight wearables while under-weighting pain/soreness/stress.

Recommended direction:

- Add a `subjective_daily_checkin` table or API endpoint.
- Make coach state explicitly separate observed vs missing vs assumed data.

#### 8. Stored procedure boundary is implicit

API/Plan services call DAL wrappers such as `get_plan_for_day`, `get_plan_for_week`, `get_metrics_overview`, likely backed by database functions.

Risk:

- Python repo does not fully explain behaviour if DB schema/functions are not version-controlled here.
- Production behaviour may depend on untracked database state.

Recommended direction:

- Add `/db/migrations` or `/sql` as first-class source-controlled artefacts.
- Document stored procedures and views alongside Python service methods.

#### 9. Observability appears log-file centric

`/logs` reads a configured history log. Sync output is also appended to a log file from cron.

Risk:

- Log scraping rather than structured state.
- Harder to distinguish partial source failure from total success.
- Operational diagnosis depends on filesystem access and log rotation behaviour.

Recommended direction:

- Persist sync runs and source statuses to DB.
- Expose `/sync_status` and `/last_successful_sync` endpoints.
- Keep text log as secondary human-readable audit.

#### 10. Tests exist but governance maturity is unclear

There are useful tests for plan building, readiness, body-age, sync logging, DAL and integration scenarios. However, rapid-growth symptoms suggest the tests may not yet enforce architectural boundaries.

Recommended direction:

- Add architecture tests:
  - domain must not import infrastructure/API/CLI.
  - infrastructure must not import CLI.
  - API must not contain business calculations beyond request validation and response shaping.
- Add contract tests for `/coach_state` response shape.
- Add migration tests for DB functions if SQL is added to repo.

---

## 5. Recommended controlled refactor sequence

Do not change feature set first. Stabilise understanding and boundaries.

### Phase 1 — Documentation and freeze

1. Keep this document as the human-readable first pass.
2. Generate AST inventory locally:
   - every `.py` file
   - every class
   - every function/method
   - imports
   - call graph where possible
3. Commit generated inventory as `docs/generated/object_inventory.md`.
4. Add a rule: no new features until undocumented modules are documented.

### Phase 2 — Safety rails

1. Add `/sync_status` backed by persisted DB run status.
2. Remove or deprecate query-string API key support.
3. Add webhook event/ref validation.
4. Wrap subprocess jobs in tracked job records.
5. Add FastAPI lifespan management for DAL pool.

### Phase 3 — Architecture boundaries

1. Split `PostgresDal` into repositories behind interfaces.
2. Consolidate duplicate mappers/services/token modules.
3. Move thresholds into config/data.
4. Add import-boundary tests.
5. Add API response schema models.

### Phase 4 — Domain maturity

1. Persist subjective readiness inputs.
2. Version coaching rules.
3. Separate raw observations, derived metrics, assumptions and coaching recommendations.
4. Add regression test fixtures for real historical days: green/amber/red, missed sync, long run fatigue, underfueling, deload.

---

## 6. Immediate open questions for the next pass

1. Are database schema and stored procedures version-controlled anywhere else?
2. Is the Pi deployment script tracked in this repo or only on the device?
3. Should Custom GPT access be header-only, or does the action setup require query-string fallback?
4. Which source should be authoritative for training plans: Python-generated plan objects or DB stored procedures/views?
5. Are Apple Health exports append-only and idempotent by source UUID/hash, or can re-imports duplicate data?
6. Does Wger sync pull from Wger as source of truth, push to Wger as target, or both?
7. Should Telegram be treated as a UI adapter only, or does it contain business command logic?

---

## 7. Next documentation pass needed

This file should be followed by an automated inventory generated from a real local checkout, for example:

```bash
python scripts/generate_object_inventory.py > docs/generated/object_inventory.md
```

That generated output should include:

- file path
- module docstring
- imports
- classes
- methods
- functions
- decorators
- public/private classification
- outbound dependencies
- detected side effects

This would turn the current controlled human review into a complete governed source-of-truth document.
