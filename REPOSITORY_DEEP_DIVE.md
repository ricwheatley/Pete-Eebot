# Repository Module and Function Inventory

## Pass 1: Systematic object-by-object inventory

### `mocks/psycopg_mock/__init__.py`
- **Module purpose (docstring):** Minimal fallback implementation of the :mod:`psycopg` package for tests. This project normally depends on the third-party ``psycopg`` package to build PostgreSQL connection strings. The automated test environment used here does not provide that dependency, so this lightweight shim exposes the subset of the API that the application uses. If the real dependency is installed it will take precedence on ``PYTHONPATH``, so this module only activates when ``psycopg`` is absent.
- **Key imports:** conninfo
- **Top-level objects:** none

### `mocks/psycopg_mock/conninfo.py`
- **Module purpose (docstring):** Lightweight subset of :mod:`psycopg.conninfo` used in tests.
- **Key imports:** __future__, typing
- **Top-level objects:**
  - `_quote` (function, line 8): No docstring; inferred from name/signature.
  - `make_conninfo` (function, line 17): Build a libpq-style connection string. This intentionally mirrors the behaviour that the project depends on without requiring the external ``psycopg`` package in the test environme…

### `mocks/pydantic_mock/__init__.py`
- **Module purpose (docstring):** Simplified subset of the :mod:`pydantic` API used in tests.
- **Key imports:** __future__, dataclasses, typing
- **Top-level objects:**
  - `FieldInfo` (class, line 9): Stores metadata about a configured field.
  - `FieldInfo.__init__` (method, line 12): No docstring; inferred from name/signature.
  - `Field` (function, line 17): Return a lightweight descriptor representing field configuration.
  - `model_validator` (function, line 23): Decorator that tags a method as a model validator.
  - `SecretStr` (class, line 34): Minimal drop-in replacement for :class:`pydantic.SecretStr`.
  - `SecretStr.__init__` (method, line 39): No docstring; inferred from name/signature.
  - `SecretStr.get_secret_value` (method, line 42): No docstring; inferred from name/signature.
  - `SecretStr.__str__` (method, line 45): No docstring; inferred from name/signature.

### `mocks/pydantic_settings_mock/__init__.py`
- **Module purpose (docstring):** Simplified :mod:`pydantic_settings` replacement for the test environment.
- **Key imports:** __future__, datetime, os, pathlib, pydantic, typing
- **Top-level objects:**
  - `SettingsConfigDict` (class, line 13): Placeholder compatible with the real ``SettingsConfigDict``.
  - `_coerce_value` (function, line 20): No docstring; inferred from name/signature.
  - `BaseSettings` (class, line 61): Very small subset of :class:`pydantic_settings.BaseSettings`.
  - `BaseSettings.__init__` (method, line 66): No docstring; inferred from name/signature.
  - `BaseSettings._run_model_validators` (method, line 79): Execute any validators registered via ``model_validator``.
  - `BaseSettings._load_value` (method, line 96): No docstring; inferred from name/signature.

### `mocks/requests_mock/__init__.py`
- **Module purpose (docstring):** Minimal stub of the :mod:`requests` package for offline tests.
- **Key imports:** __future__, typing
- **Top-level objects:**
  - `RequestException` (class, line 8): Base exception class matching the real ``requests`` API.
  - `_StubResponse` (class, line 12): No docstring; inferred from name/signature.
  - `_StubResponse.__init__` (method, line 13): No docstring; inferred from name/signature.
  - `_StubResponse.raise_for_status` (method, line 17): No docstring; inferred from name/signature.
  - `_StubResponse.json` (method, line 21): No docstring; inferred from name/signature.
  - `post` (function, line 25): No docstring; inferred from name/signature.
  - `get` (function, line 29): No docstring; inferred from name/signature.

### `pete_e/api.py`
- **Key imports:** datetime, fastapi, fastapi.responses, hashlib, hmac, pathlib, pete_e.application.api_services, pete_e.application.sync, pete_e.cli.status, pete_e.config, pete_e.infrastructure.postgres_dal, subprocess ...
- **Top-level objects:**
  - `_secret_to_str` (function, line 26): No docstring; inferred from name/signature.
  - `_configured_api_key` (function, line 33): No docstring; inferred from name/signature.
  - `_configured_webhook_secret` (function, line 40): No docstring; inferred from name/signature.
  - `_configured_deploy_script_path` (function, line 47): No docstring; inferred from name/signature.
  - `get_dal` (function, line 57): No docstring; inferred from name/signature.
  - `get_metrics_service` (function, line 64): No docstring; inferred from name/signature.
  - `get_plan_service` (function, line 71): No docstring; inferred from name/signature.
  - `get_status_service` (function, line 78): No docstring; inferred from name/signature.
  - `validate_api_key` (function, line 85): No docstring; inferred from name/signature.
  - `root_get` (function, line 94): No docstring; inferred from name/signature.
  - `root_post` (function, line 99): No docstring; inferred from name/signature.
  - `metrics_overview` (function, line 105): Run sp_metrics_overview(date) and return columns + rows as JSON. Requires API key in header (X-API-Key) or query string (?api_key=).
  - `daily_summary` (function, line 128): Return one normalized daily summary with units, source and quality metadata.
  - `recent_workouts` (function, line 146): Return recent running and strength sessions for coaching context.
  - `coach_state` (function, line 165): Return compact derived coaching state for a custom GPT action.
  - `goal_state` (function, line 183): Return long-range goals, target dates and strength training maxes.
  - `user_notes` (function, line 195): Return persisted subjective notes when configured, otherwise an empty placeholder.
  - `plan_context` (function, line 211): Return current plan phase and deload context.
  - `sse` (function, line 230): No docstring; inferred from name/signature.
  - `plan_for_day` (function, line 243): Run sp_plan_for_day(date) and return the scheduled workouts for that day.
  - `plan_for_week` (function, line 266): Run sp_plan_for_week(start_date) and return the scheduled workouts for that week.
  - `status` (function, line 288): Expose the CLI health check results via the API.
  - `sync` (function, line 320): Trigger the same sync workflow exposed via the CLI.
  - `logs` (function, line 347): Return the last ``lines`` entries from the Pete-Eebot history log.
  - `run_pete_plan_async` (function, line 371): No docstring; inferred from name/signature.
  - `github_webhook` (function, line 383): GitHub push webhook. Validates signature, then triggers deploy.sh asynchronously.

### `pete_e/application/__init__.py`
- **Top-level objects:** none

### `pete_e/application/api_services.py`
- **Module purpose (docstring):** Application services powering the public API endpoints.
- **Key imports:** __future__, datetime, decimal, pete_e.config, pete_e.infrastructure.postgres_dal, pete_e.utils, typing
- **Top-level objects:**
  - `_json_safe` (function, line 75): No docstring; inferred from name/signature.
  - `_avg` (function, line 87): No docstring; inferred from name/signature.
  - `_window_rows` (function, line 91): No docstring; inferred from name/signature.
  - `_numeric_values` (function, line 100): No docstring; inferred from name/signature.
  - `_sum_field` (function, line 109): No docstring; inferred from name/signature.
  - `_DateParserMixin` (class, line 114): Shared helpers for services that accept ISO date strings.
  - `_DateParserMixin._parse_iso_date` (method, line 118): No docstring; inferred from name/signature.
  - `MetricsService` (class, line 125): Read-only service exposing metrics related stored procedures.
  - `MetricsService.__init__` (method, line 128): No docstring; inferred from name/signature.
  - `MetricsService.overview` (method, line 131): No docstring; inferred from name/signature.
  - `MetricsService.daily_summary` (method, line 136): No docstring; inferred from name/signature.
  - `MetricsService.recent_workouts` (method, line 181): No docstring; inferred from name/signature.
  - `MetricsService.coach_state` (method, line 202): No docstring; inferred from name/signature.
  - `MetricsService.goal_state` (method, line 291): No docstring; inferred from name/signature.
  - `MetricsService.user_notes` (method, line 313): No docstring; inferred from name/signature.
  - `MetricsService.plan_context` (method, line 323): No docstring; inferred from name/signature.
  - `MetricsService._source_for_metric` (method, line 352): No docstring; inferred from name/signature.
  - `MetricsService._completeness_pct` (method, line 360): No docstring; inferred from name/signature.
  - `MetricsService._run_load` (method, line 370): No docstring; inferred from name/signature.
  - `MetricsService._coach_data_quality` (method, line 384): No docstring; inferred from name/signature.
  - `MetricsService._possible_underfueling` (method, line 409): No docstring; inferred from name/signature.
  - `MetricsService._readiness_state` (method, line 423): No docstring; inferred from name/signature.
  - `MetricsService._latest_training_maxes` (method, line 447): No docstring; inferred from name/signature.
  - `MetricsService._latest_training_max_date` (method, line 451): No docstring; inferred from name/signature.
  - `MetricsService._next_deload_week` (method, line 456): No docstring; inferred from name/signature.
  - `PlanService` (class, line 467): Service for read-only access to stored plan snapshots.
  - `PlanService.__init__` (method, line 470): No docstring; inferred from name/signature.
  - `PlanService.for_day` (method, line 473): No docstring; inferred from name/signature.
  - `PlanService.for_week` (method, line 478): No docstring; inferred from name/signature.
  - `StatusService` (class, line 484): Service wrapper for status checks to align with API layers.
  - `StatusService.__init__` (method, line 487): No docstring; inferred from name/signature.
  - `StatusService.run_checks` (method, line 490): No docstring; inferred from name/signature.

### `pete_e/application/apple_dropbox_ingest.py`
- **Module purpose (docstring):** Application entry point for the Apple Health Dropbox ingest.
- **Key imports:** __future__, pete_e.domain.daily_sync, pete_e.infrastructure.apple_health_ingestor, pete_e.infrastructure.di_container, typing
- **Top-level objects:**
  - `_resolve_ingestor` (function, line 26): No docstring; inferred from name/signature.
  - `run_apple_health_ingest` (function, line 31): Execute the Apple Health ingest using dependency-injected collaborators.
  - `get_last_successful_import_timestamp` (function, line 42): Read the checkpoint stored by the ingest workflow.

### `pete_e/application/catalog_sync.py`
- **Module purpose (docstring):** Application service responsible for syncing the wger catalog.
- **Key imports:** __future__, pete_e.domain, pete_e.infrastructure, pete_e.infrastructure.postgres_dal, pete_e.infrastructure.wger_client, typing
- **Top-level objects:**
  - `CatalogSyncService` (class, line 13): Refreshes the local wger catalog and seeds assistance metadata.
  - `CatalogSyncService.__init__` (method, line 16): No docstring; inferred from name/signature.
  - `CatalogSyncService.run` (method, line 24): Execute the full catalog refresh workflow.

### `pete_e/application/exceptions.py`
- **Module purpose (docstring):** Custom exception hierarchy for Pete-Eebot application orchestration.
- **Key imports:** __future__
- **Top-level objects:**
  - `ApplicationError` (class, line 6): Base exception for application orchestration failures.
  - `ValidationError` (class, line 10): Raised when weekly validation or calibration cannot be completed.
  - `PlanRolloverError` (class, line 14): Raised when cycle rollover or related planning operations fail.
  - `DataAccessError` (class, line 18): Raised when persistence layer calls fail during orchestration.

### `pete_e/application/orchestrator.py`
- **Module purpose (docstring):** Main orchestrator for Pete-Eebot's core logic. Delegates tasks to specialized services for clarity and maintainability.
- **Key imports:** __future__, contextlib, dataclasses, datetime, decimal, pete_e.application.exceptions, pete_e.application.plan_generation, pete_e.application.services, pete_e.application.validation_service, pete_e.domain, pete_e.domain.cycle_service, pete_e.domain.daily_sync ...
- **Top-level objects:**
  - `WeeklyCalibrationResult` (class, line 38): No docstring; inferred from name/signature.
  - `DailyAutomationResult` (class, line 44): No docstring; inferred from name/signature.
  - `CycleRolloverResult` (class, line 55): No docstring; inferred from name/signature.
  - `WeeklyAutomationResult` (class, line 63): No docstring; inferred from name/signature.
  - `_coerce_metric_value` (function, line 69): No docstring; inferred from name/signature.
  - `_build_metrics_overview_payload` (function, line 75): No docstring; inferred from name/signature.
  - `Orchestrator` (class, line 92): Coordinates Pete-Eebot workflows by delegating to application services.
  - `Orchestrator.__init__` (method, line 95): Initialize orchestrator dependencies.
  - `Orchestrator._hold_plan_generation_lock` (method, line 138): No docstring; inferred from name/signature.
  - `Orchestrator.run_weekly_calibration` (method, line 145): Runs validation and progression on the upcoming week. This method is now much simpler.
  - `Orchestrator.run_cycle_rollover` (method, line 174): Handles the end-of-cycle logic: creating the next block and exporting week 1. This is now a clean, high-level workflow.
  - `Orchestrator.run_end_to_end_week` (method, line 226): The main entry point for the Sunday review.
  - `Orchestrator.run_daily_sync` (method, line 289): Orchestrates the daily sync of all data sources.
  - `Orchestrator.run_withings_only_sync` (method, line 296): Runs only the Withings portion of the sync and refreshes views.
  - `Orchestrator.run_end_to_end_day` (method, line 301): Run the daily sync and, when appropriate, send the daily summary.
  - `Orchestrator.generate_and_deploy_next_plan` (method, line 345): Create the next 4-week plan block and export week one.
  - `Orchestrator.generate_strength_test_week` (method, line 375): Create and export a one-week strength-test block.
  - `Orchestrator.close` (method, line 405): Closes any open connections, like the database pool.
  - `Orchestrator.get_daily_summary` (method, line 413): Return the conversational morning narrative for the chosen day.
  - `Orchestrator.build_trainer_message` (method, line 453): Compose Pierre's trainer check-in for the supplied date.
  - `Orchestrator.send_telegram_message` (method, line 476): Proxy to the Telegram client while providing defensive logging.
  - `Orchestrator._build_morning_run_guidance` (method, line 493): Return run-specific back-off advice for the morning report.
  - `Orchestrator._build_trainer_context` (method, line 548): Construct contextual hints for the trainer narrative.
  - `Orchestrator._load_plan_for_day` (method, line 558): Fetch the active plan rows for the given day, normalising shape.
  - `Orchestrator._summarise_session` (method, line 593): Generate a short descriptor for the day's planned training.
  - `Orchestrator._resolve_review_anchor` (method, line 622): Normalize the weekly automation anchor to the most recent Sunday.
  - `Orchestrator._next_week_start` (method, line 632): Return the Monday immediately after the supplied anchor date.
  - `Orchestrator._resolve_export_week_number` (method, line 642): Determine whether the athlete should advance or repeat the prior week.
  - `Orchestrator._export_active_week` (method, line 675): Push the upcoming training week to wger for the active plan.
  - `Orchestrator._summarise_active_plan` (method, line 752): Collect lightweight debugging info for the weekly rollover checkpoint.
  - `Orchestrator._plan_week_index` (method, line 788): Return the 1-based week index for the supplied start and reference dates.
  - `Orchestrator._coerce_date` (method, line 800): Best-effort conversion of DAL payloads to ``date`` objects.
  - `Orchestrator._coerce_positive_int` (method, line 815): Helper shared with plan snapshots to keep log payloads legible.

### `pete_e/application/plan_context_service.py`
- **Key imports:** __future__, dataclasses, datetime, pete_e.application.exceptions, pete_e.domain.data_access, pete_e.domain.validation, typing
- **Top-level objects:**
  - `ApplicationPlanService` (class, line 18): Application-level helper that loads plan context for domain logic.
  - `ApplicationPlanService.get_plan_context` (method, line 23): Fetch the current plan context, falling back to the requested week.

### `pete_e/application/plan_generation.py`
- **Module purpose (docstring):** Application service responsible for generating training plans.
- **Key imports:** __future__, contextlib, datetime, pete_e.application.services, pete_e.infrastructure, pete_e.infrastructure.postgres_dal, pete_e.infrastructure.wger_client, psycopg, typing
- **Top-level objects:**
  - `PlanGenerationService` (class, line 17): Coordinates plan creation and optional export to wger.
  - `PlanGenerationService.__init__` (method, line 20): No docstring; inferred from name/signature.
  - `PlanGenerationService.run` (method, line 28): Create a 5/3/1 block starting at ``start_date`` and export week one.

### `pete_e/application/progression_service.py`
- **Key imports:** __future__, dataclasses, pete_e.config, pete_e.domain.data_access, pete_e.domain.progression, pete_e.infrastructure, typing
- **Top-level objects:**
  - `_extract_exercise_ids` (function, line 12): No docstring; inferred from name/signature.
  - `ProgressionService` (class, line 29): Application service that prepares data for progression logic.
  - `ProgressionService.__init__` (method, line 32): No docstring; inferred from name/signature.
  - `ProgressionService.calibrate_plan_week` (method, line 35): No docstring; inferred from name/signature.

### `pete_e/application/services.py`
- **Module purpose (docstring):** Contains high-level services that orchestrate domain logic and infrastructure. This layer is responsible for coordinating tasks like plan creation and export.
- **Key imports:** __future__, datetime, json, pete_e.application.strength_test, pete_e.application.validation_service, pete_e.config, pete_e.domain, pete_e.domain.entities, pete_e.domain.plan_factory, pete_e.domain.running_planner, pete_e.domain.validation, pete_e.infrastructure ...
- **Top-level objects:**
  - `PlanService` (class, line 25): Service for creating and managing training plans.
  - `PlanService.__init__` (method, line 28): Initializes the service with a data access layer.
  - `PlanService.create_and_persist_531_block` (method, line 35): Creates and persists a new 4-week 5/3/1 block. Orchestrates fetching TMs, building the plan object, and saving it.
  - `PlanService._load_recent_health_metrics` (method, line 64): No docstring; inferred from name/signature.
  - `PlanService._load_recent_running_workouts` (method, line 74): No docstring; inferred from name/signature.
  - `PlanService._running_goal_from_settings` (method, line 85): No docstring; inferred from name/signature.
  - `PlanService.create_and_persist_strength_test_week` (method, line 93): Creates and persists a new 1-week strength test plan.
  - `PlanService.create_next_plan_for_cycle` (method, line 104): Create the next block in the macrocycle and persist it.
  - `WgerExportService` (class, line 126): Service for validating plans and exporting them to wger.
  - `WgerExportService.__init__` (method, line 129): No docstring; inferred from name/signature.
  - `WgerExportService.export_plan_week` (method, line 143): Validates, prepares, and pushes a single training week to wger. (Logic migrated from wger_sender.py and wger_exporter.py)
  - `WgerExportService._fallback_routine_name` (method, line 322): No docstring; inferred from name/signature.
  - `WgerExportService._apply_running_backoff_to_payload` (method, line 326): Downgrade run intensity in the exported week when readiness is poor.
  - `WgerExportService._build_payload_from_rows` (method, line 390): Transforms flat DB rows into the nested payload structure for export.
  - `WgerExportService._annotate_week_payload` (method, line 422): Enrich the payload with protocol notes and rest guidance.
  - `WgerExportService._entry_comment_for_api` (method, line 492): No docstring; inferred from name/signature.
  - `WgerExportService._apply_slot_entry_configs` (method, line 499): No docstring; inferred from name/signature.
  - `WgerExportService._expand_stretch_routines_for_export` (method, line 541): No docstring; inferred from name/signature.
  - `WgerExportService._expand_stretch_entry` (method, line 548): No docstring; inferred from name/signature.
  - `WgerExportService._resolve_export_exercise_id` (method, line 609): No docstring; inferred from name/signature.
  - `WgerExportService._stretch_export_description` (method, line 632): No docstring; inferred from name/signature.

### `pete_e/application/strength_test.py`
- **Module purpose (docstring):** Strength-test evaluation helpers used to refresh training maxes.
- **Key imports:** __future__, dataclasses, datetime, pete_e.domain, pete_e.infrastructure, pete_e.infrastructure.postgres_dal, typing
- **Top-level objects:**
  - `StrengthTestEvaluationResult` (class, line 18): Summary of a completed strength-test recalibration pass.
  - `_LoggedSet` (class, line 29): No docstring; inferred from name/signature.
  - `StrengthTestService` (class, line 36): Convert logged AMRAP strength-test results into new training maxes.
  - `StrengthTestService.__init__` (method, line 39): No docstring; inferred from name/signature.
  - `StrengthTestService.evaluate_latest_test_week_and_update_tms` (method, line 42): Evaluate the latest test week, if available, and upsert training maxes.
  - `StrengthTestService._planned_test_dates` (method, line 129): No docstring; inferred from name/signature.
  - `StrengthTestService._best_logged_set` (method, line 143): No docstring; inferred from name/signature.
  - `StrengthTestService._row_to_logged_set` (method, line 167): No docstring; inferred from name/signature.
  - `StrengthTestService._round_to_2p5` (method, line 183): No docstring; inferred from name/signature.
  - `StrengthTestService._e1rm_epley` (method, line 187): No docstring; inferred from name/signature.
  - `StrengthTestService._coerce_date` (method, line 191): No docstring; inferred from name/signature.
  - `StrengthTestService._coerce_int` (method, line 206): No docstring; inferred from name/signature.
  - `StrengthTestService._coerce_float` (method, line 219): No docstring; inferred from name/signature.

### `pete_e/application/sync.py`
- **Module purpose (docstring):** Daily sync orchestrator for Pete-Eebot. This script acts as a simple entry point for the synchronization process, which is orchestrated by the Orchestrator class. It's intended to be run from the main CLI.
- **Key imports:** __future__, dataclasses, pete_e.infrastructure, tenacity, typing
- **Top-level objects:**
  - `SyncResult` (class, line 38): Aggregate outcome of a sync run after retries complete.
  - `SyncResult.summary_line` (method, line 48): No docstring; inferred from name/signature.
  - `SyncResult._build_source_notes` (method, line 66): No docstring; inferred from name/signature.
  - `SyncResult.log_level` (method, line 79): No docstring; inferred from name/signature.
  - `SyncAttemptFailedError` (class, line 83): Represents a failed sync attempt that should be retried.
  - `SyncAttemptFailedError.__init__` (method, line 86): No docstring; inferred from name/signature.
  - `_build_orchestrator` (function, line 96): No docstring; inferred from name/signature.
  - `_build_failure_message` (function, line 105): Create a consistent failure summary for retry exhaustion.
  - `_run_with_retry` (function, line 122): No docstring; inferred from name/signature.
  - `run_sync_with_retries` (function, line 243): Run the full multi-source sync via the Orchestrator with retries.
  - `run_withings_only_with_retries` (function, line 273): Run the Withings-only sync with the same retry semantics as the full sync.

### `pete_e/application/telegram_listener.py`
- **Module purpose (docstring):** Short-running Telegram command listener for Pete-Eebot.
- **Key imports:** __future__, importlib, json, pathlib, pete_e.config, pete_e.infrastructure, pete_e.infrastructure.di_container, pete_e.infrastructure.telegram_client, typing, typing_extensions
- **Top-level objects:**
  - `_LazyModuleProxy` (class, line 18): Provides attribute access to a module loaded only when required.
  - `_LazyModuleProxy.__init__` (method, line 21): No docstring; inferred from name/signature.
  - `_LazyModuleProxy._load` (method, line 25): No docstring; inferred from name/signature.
  - `_LazyModuleProxy.__getattribute__` (method, line 32): No docstring; inferred from name/signature.
  - `_LazyModuleProxy.__setattr__` (method, line 43): No docstring; inferred from name/signature.
  - `_OrchestratorProtocol` (class, line 53): No docstring; inferred from name/signature.
  - `_OrchestratorProtocol.run_end_to_end_day` (method, line 54): No docstring; inferred from name/signature.
  - `_OrchestratorProtocol.generate_strength_test_week` (method, line 57): No docstring; inferred from name/signature.
  - `TelegramCommandListener` (class, line 61): Polls Telegram once and routes supported bot commands.
  - `TelegramCommandListener.__init__` (method, line 64): No docstring; inferred from name/signature.
  - `TelegramCommandListener._default_offset_path` (method, line 82): No docstring; inferred from name/signature.
  - `TelegramCommandListener._load_offset` (method, line 86): No docstring; inferred from name/signature.
  - `TelegramCommandListener._persist_offset` (method, line 107): No docstring; inferred from name/signature.
  - `TelegramCommandListener._next_offset` (method, line 114): No docstring; inferred from name/signature.
  - `TelegramCommandListener._get_orchestrator` (method, line 120): No docstring; inferred from name/signature.
  - `TelegramCommandListener._handle_summary` (method, line 131): No docstring; inferred from name/signature.
  - `TelegramCommandListener._handle_sync` (method, line 142): No docstring; inferred from name/signature.
  - `TelegramCommandListener._handle_lets_begin` (method, line 163): No docstring; inferred from name/signature.
  - `TelegramCommandListener._extract_command` (method, line 184): No docstring; inferred from name/signature.
  - `TelegramCommandListener.listen_once` (method, line 192): Fetch a batch of updates, handle commands, and persist the offset.

### `pete_e/application/validation_service.py`
- **Key imports:** __future__, dataclasses, datetime, pete_e.domain.data_access, pete_e.domain.validation, pete_e.infrastructure, plan_context_service, typing
- **Top-level objects:**
  - `ValidationService` (class, line 21): Application service responsible for coordinating validation data.
  - `ValidationService.__init__` (method, line 24): No docstring; inferred from name/signature.
  - `ValidationService._load_validation_payload` (method, line 32): No docstring; inferred from name/signature.
  - `ValidationService._build_adherence_snapshot` (method, line 59): No docstring; inferred from name/signature.
  - `ValidationService.get_adherence_snapshot` (method, line 94): Expose adherence snapshot for consumers that need summary data.
  - `ValidationService.validate_and_adjust_plan` (method, line 106): No docstring; inferred from name/signature.

### `pete_e/application/wger_sender.py`
- **Module purpose (docstring):** Send validated training plans to the Wger API.
- **Key imports:** datetime, hashlib, json, pete_e.application.services, pete_e.application.validation_service, pete_e.domain.data_access, pete_e.domain.validation, pete_e.infrastructure, pete_e.infrastructure.wger_client, typing
- **Top-level objects:**
  - `_summarize_adherence` (function, line 15): No docstring; inferred from name/signature.
  - `_payload_checksum` (function, line 31): No docstring; inferred from name/signature.
  - `_normalise_weight` (function, line 35): No docstring; inferred from name/signature.
  - `_flatten_week_payload` (function, line 44): No docstring; inferred from name/signature.
  - `_summarize_adherence` (function, line 71): No docstring; inferred from name/signature.
  - `push_week` (function, line 88): Push a single plan week to Wger with idempotency guards.

### `pete_e/application/wger_sync.py`
- **Module purpose (docstring):** Fetch the Wger exercise catalog and upsert it into the PostgreSQL database. Also seeds the main lifts and assistance pools after the catalog is refreshed.
- **Key imports:** pete_e.infrastructure, pete_e.infrastructure.postgres_dal, pete_e.infrastructure.wger_client, pete_e.infrastructure.wger_seeder, pete_e.infrastructure.wger_writer, sys, typing
- **Top-level objects:**
  - `_pick_english_translation` (function, line 20): Prefers English (language ID 2); falls back to any available translation.
  - `run_wger_catalog_refresh` (function, line 36): Orchestrates the end-to-end process of refreshing the WGER catalogue. Fetches all data from the WGER API and bulk-upserts it into the database.

### `pete_e/cli/messenger.py`
- **Module purpose (docstring):** Main Command-Line Interface for the Pete-Eebot application. This script provides a single entry point for all major operations, including running the daily data sync, ingesting new data, and sending notifications.
- **Key imports:** csv, datetime, json, os, pathlib, pete_e.application.apple_dropbox_ingest, pete_e.application.exceptions, pete_e.application.plan_generation, pete_e.application.sync, pete_e.application.wger_sender, pete_e.cli.status, pete_e.cli.telegram ...
- **Top-level objects:**
  - `_echo_error` (function, line 107): No docstring; inferred from name/signature.
  - `_exit_for_application_error` (function, line 115): Render a friendly error message for application-layer failures.
  - `_build_orchestrator` (function, line 130): Lazy import helper to avoid CLI/orchestrator circular dependencies.
  - `_format_body_age_line` (function, line 136): No docstring; inferred from name/signature.
  - `_coerce_summary_date` (function, line 149): No docstring; inferred from name/signature.
  - `_format_body_comp_line` (function, line 162): No docstring; inferred from name/signature.
  - `_format_hrv_line` (function, line 210): No docstring; inferred from name/signature.
  - `_collect_trend_samples` (function, line 267): No docstring; inferred from name/signature.
  - `_build_trend_paragraph` (function, line 288): No docstring; inferred from name/signature.
  - `_append_line` (function, line 298): No docstring; inferred from name/signature.
  - `build_daily_summary` (function, line 324): Generate the daily summary narrative for the requested date.
  - `send_daily_summary` (function, line 355): Send the daily summary via Telegram and return the content that was sent.
  - `build_trainer_summary` (function, line 379): Build Pierre's trainer message for the provided day (defaults to today).
  - `send_trainer_summary` (function, line 390): Send Pierre's trainer message via Telegram and return the content.
  - `build_weekly_plan_overview` (function, line 414): Build a weekly plan overview with key workouts and a motivational tip.
  - `_patch_cli_runner_boolean_flags` (function, line 508): No docstring; inferred from name/signature.
  - `sync` (function, line 551): Run the daily data synchronization. Fetches the latest data from all sources (Withings, Apple, Wger), updates the database, and recalculates body age.
  - `withings_sync` (function, line 574): Run only the Withings portion of the sync pipeline.
  - `status` (function, line 592): Quick health check for database and external service integrations.
  - `ingest_apple` (function, line 603): Ingest Apple Health data delivered via Dropbox. Downloads new HealthAutoExport files from Dropbox, parses them, and persists the resulting metrics to the database.
  - `plan` (function, line 631): Generate and deploy the next 4-week training plan block.
  - `lets_begin` (function, line 678): Start a new 13-week 5/3/1 macrocycle and seed the strength test week. Uses the Orchestrator’s PlanGenerationService to build and export week 1.
  - `message` (function, line 740): Generate and optionally send messages (daily summary, trainer check-in, or weekly plan).
  - `morning_report` (function, line 794): Generate the conversational morning report and optionally send it.
  - `refresh_withings_tokens` (function, line 835): Force a Withings token refresh and save the new tokens to disk.
  - `withings_auth_url` (function, line 851): Print the Withings authorization URL for first-time setup. Open it in your browser, log in, and approve Pete-Eebot.
  - `withings_exchange_code` (function, line 862): Exchange an authorization code (from Withings redirect) for tokens. Saves tokens to ~/.config/pete_eebot/.withings_tokens.json for future use.
  - `logs` (function, line 881): Print the last N lines of the Pete-Eebot log file, optionally filtered by tag. Examples: pete logs → last 50 lines pete logs 200 → last 200 lines pete logs HB → last 50 lines conta…
  - `db` (function, line 974): Run an ad-hoc SQL query. Supports {date} substitution, optional row limit, and CSV/JSON export.
  - `metrics` (function, line 1102): Runs sp_metrics_overview for the given date or date range. Defaults to yesterday if no date is provided.

### `pete_e/cli/status.py`
- **Module purpose (docstring):** Health check command support for the pete CLI.
- **Key imports:** __future__, dataclasses, pete_e.infrastructure.apple_dropbox_client, pete_e.infrastructure.db_conn, pete_e.infrastructure.telegram_client, pete_e.infrastructure.wger_client, pete_e.infrastructure.withings_client, psycopg, time, typing
- **Top-level objects:**
  - `CheckResult` (class, line 21): Represents a single dependency check outcome.
  - `_format_duration` (function, line 29): No docstring; inferred from name/signature.
  - `_format_exception` (function, line 36): No docstring; inferred from name/signature.
  - `check_database` (function, line 43): No docstring; inferred from name/signature.
  - `check_dropbox` (function, line 55): No docstring; inferred from name/signature.
  - `check_withings` (function, line 67): No docstring; inferred from name/signature.
  - `check_telegram` (function, line 79): No docstring; inferred from name/signature.
  - `check_wger` (function, line 91): No docstring; inferred from name/signature.
  - `run_status_checks` (function, line 103): Executes dependency checks, allowing override for testing.
  - `render_results` (function, line 122): No docstring; inferred from name/signature.

### `pete_e/cli/telegram.py`
- **Module purpose (docstring):** CLI helpers for Telegram command listening.
- **Key imports:** __future__, pathlib, pete_e.infrastructure, typer, typing, typing_extensions
- **Top-level objects:**
  - `_build_listener` (function, line 20): No docstring; inferred from name/signature.
  - `telegram` (function, line 35): Telegram command utilities.

### `pete_e/config/__init__.py`
- **Key imports:** config
- **Top-level objects:** none

### `pete_e/config/config.py`
- **Module purpose (docstring):** Centralised config for the entire application. This module consolidates all configuration settings, loading sensitive values from environment variables and providing typed, validated access to them through a singleton `settings` object.
- **Key imports:** datetime, os, pathlib, pydantic, pydantic_settings, typing
- **Top-level objects:**
  - `_discover_project_root` (function, line 20): Return a project root and env file path without assuming ``.env`` exists.
  - `_discover_app_root` (function, line 42): Resolve the root used for locating bundled application resources.
  - `Settings` (class, line 57): Centralised and validated application settings.
  - `Settings.build_database_url` (method, line 150): Dynamically construct the ``DATABASE_URL`` after validation.
  - `Settings.log_path` (method, line 167): Return the resolved application log path without writing to stdout.
  - `Settings.consume_log_path_notice` (method, line 173): Return any one-time log-path fallback notice.
  - `Settings._resolve_log_path` (method, line 184): No docstring; inferred from name/signature.
  - `Settings.phrases_path` (method, line 205): Path to the tagged phrases resource file.
  - `_build_conninfo` (function, line 211): Return a libpq-compatible connection string from keyword parameters.
  - `_coerce_secret` (function, line 236): No docstring; inferred from name/signature.
  - `_to_bool` (function, line 242): No docstring; inferred from name/signature.
  - `_coerce_type` (function, line 246): No docstring; inferred from name/signature.
  - `get_env` (function, line 258): Return a configuration value resolving environment overrides consistently.

### `pete_e/domain/__init__.py`
- **Top-level objects:** none

### `pete_e/domain/body_age.py`
- **Module purpose (docstring):** Analytical body-age helpers for Pete-E. Production body-age values are computed inside PostgreSQL via the ``sp_upsert_body_age`` stored procedure (invoked by ``PostgresDal.compute_body_age_for_date``). The Python implementation below mirrors that logic so notebooks and ad-hoc analysis can stay in sync with the database output. As the Apple Health ingestion moved to a normalised schema, records now tend to expose "flat" keys (``steps``, ``sleep_asleep_minutes`` …) instead of the nested dictionaries that the first iteration of the function expected. The helper therefore accepts either structure.
- **Key imports:** dataclasses, datetime, pete_e.utils, typing
- **Top-level objects:**
  - `BodyAgeTrend` (class, line 21): Latest body age reading with a seven-day trend.
  - `_clamp_score` (function, line 33): No docstring; inferred from name/signature.
  - `_score_body_fat_percent` (function, line 37): No docstring; inferred from name/signature.
  - `_score_visceral_fat_index` (function, line 47): No docstring; inferred from name/signature.
  - `_score_muscle_percent` (function, line 57): No docstring; inferred from name/signature.
  - `_row_muscle_percent` (function, line 67): No docstring; inferred from name/signature.
  - `_has_enriched_body_comp` (function, line 79): No docstring; inferred from name/signature.
  - `_calculate_body_comp_score` (function, line 91): No docstring; inferred from name/signature.
  - `_extract_body_age_value` (function, line 121): Pull a body age value from a summary row.
  - `get_body_age_trend` (function, line 131): Return the latest body age reading and its delta versus seven days prior.
  - `calculate_body_age` (function, line 204): Compute body age using rolling 7-day averages.

### `pete_e/domain/configuration.py`
- **Module purpose (docstring):** Domain configuration registry decoupled from infrastructure settings.
- **Key imports:** __future__, dataclasses, pathlib, typing
- **Top-level objects:**
  - `DomainSettings` (class, line 10): Runtime configuration values consumed by domain logic.
  - `configure` (function, line 28): Override the active :class:`DomainSettings` instance. The application layer calls this during bootstrapping with values derived from environment configuration. Tests may also overr…
  - `get_settings` (function, line 46): Return the currently configured :class:`DomainSettings`.

### `pete_e/domain/cycle_service.py`
- **Module purpose (docstring):** Domain service encapsulating cycle rollover logic.
- **Key imports:** __future__, datetime, typing
- **Top-level objects:**
  - `CycleService` (class, line 8): Provides domain logic related to training cycle transitions.
  - `CycleService.__init__` (method, line 11): Create a service instance. Args: rollover_weeks: Minimum number of weeks that must elapse before a rollover is permitted. Defaults to four weeks. trigger_weekday: The weekday (``0`…
  - `CycleService.check_and_rollover` (method, line 23): Determine whether a new training cycle should start. Args: active_plan: The currently active training plan, or ``None`` if no plan is available. reference_date: The date to evaluat…
  - `CycleService.should_rollover` (method, line 53): Backward compatible alias for :meth:`check_and_rollover`.
  - `CycleService._coerce_positive_int` (method, line 59): Best-effort conversion helper for loosely typed plan metadata.

### `pete_e/domain/daily_sync.py`
- **Module purpose (docstring):** Domain-level orchestration for daily data synchronisation.
- **Key imports:** __future__, dataclasses, datetime, pete_e.domain, typing
- **Top-level objects:**
  - `AppleHealthImportSummary` (class, line 13): Light-weight summary of an Apple Health ingest run.
  - `AppleHealthIngestResult` (class, line 24): Outcome of importing data from Apple Health.
  - `DailySyncSourceResult` (class, line 35): Result of synchronising a single upstream source.
  - `DailySyncResult` (class, line 45): Aggregate result for an entire daily sync run.
  - `DailySyncResult.as_tuple` (method, line 53): Return the format expected by the CLI retry logic.
  - `WithingsDataSource` (class, line 64): Minimal contract for loading Withings measurements.
  - `WithingsDataSource.get_summary` (method, line 67): Return a summary for ``days_back`` days in the past.
  - `DailyMetricsRepository` (class, line 71): Persistence operations required for the daily sync.
  - `DailyMetricsRepository.save_withings_daily` (method, line 74): Persist a Withings daily summary.
  - `DailyMetricsRepository.save_withings_measure_groups` (method, line 94): Persist raw Withings measure groups for future-proof analysis.
  - `DailyMetricsRepository.refresh_daily_summary` (method, line 102): Refresh the reporting view that powers the daily summary.
  - `DailyMetricsRepository.refresh_actual_view` (method, line 105): Refresh the supporting view for actual training data.
  - `AppleHealthIngestor` (class, line 109): Contract for components capable of importing Apple Health exports.
  - `AppleHealthIngestor.ingest` (method, line 112): Run the ingest and return the outcome.
  - `AppleHealthIngestor.get_last_import_timestamp` (method, line 115): Return the timestamp of the most recent successful import, if known.
  - `DailySyncService` (class, line 119): Coordinates the daily synchronisation workflow in the domain layer.
  - `DailySyncService.__init__` (method, line 122): No docstring; inferred from name/signature.
  - `DailySyncService.run_full` (method, line 133): Run the full multi-source sync.
  - `DailySyncService.run_withings_only` (method, line 143): Run only the Withings sync and refresh the daily summary.
  - `DailySyncService._sync_withings` (method, line 152): No docstring; inferred from name/signature.
  - `DailySyncService._refresh_views` (method, line 198): No docstring; inferred from name/signature.
  - `DailySyncService._ingest_apple` (method, line 220): No docstring; inferred from name/signature.
  - `DailySyncService._combine` (method, line 232): No docstring; inferred from name/signature.

### `pete_e/domain/data_access.py`
- **Key imports:** abc, datetime, typing
- **Top-level objects:**
  - `DataAccessLayer` (class, line 8): Abstract Base Class for Pete-Eebot's PostgreSQL Data Access Layer. Defines clean, DB-native operations for all sources and derived data.
  - `DataAccessLayer.save_withings_daily` (method, line 18): No docstring; inferred from name/signature.
  - `DataAccessLayer.save_withings_measure_groups` (method, line 39): Persist raw Withings measure groups for future-proof analysis.
  - `DataAccessLayer.save_wger_log` (method, line 49): No docstring; inferred from name/signature.
  - `DataAccessLayer.load_lift_log` (method, line 54): Return lift log entries grouped by exercise id.
  - `DataAccessLayer.get_daily_summary` (method, line 67): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_historical_metrics` (method, line 71): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_historical_data` (method, line 75): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_recent_running_workouts` (method, line 78): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_recent_strength_workouts` (method, line 86): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_data_for_validation` (method, line 95): Return all data required for validation for the supplied week.
  - `DataAccessLayer.refresh_daily_summary` (method, line 100): No docstring; inferred from name/signature.
  - `DataAccessLayer.compute_body_age_for_date` (method, line 104): No docstring; inferred from name/signature.
  - `DataAccessLayer.compute_body_age_for_range` (method, line 108): No docstring; inferred from name/signature.
  - `DataAccessLayer.save_training_plan` (method, line 121): Insert plan, weeks, workouts. Return plan_id.
  - `DataAccessLayer.has_any_plan` (method, line 126): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_plan` (method, line 130): No docstring; inferred from name/signature.
  - `DataAccessLayer.find_plan_by_start_date` (method, line 134): No docstring; inferred from name/signature.
  - `DataAccessLayer.mark_plan_active` (method, line 138): No docstring; inferred from name/signature.
  - `DataAccessLayer.deactivate_active_training_cycles` (method, line 145): No docstring; inferred from name/signature.
  - `DataAccessLayer.create_training_cycle` (method, line 149): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_active_training_cycle` (method, line 159): No docstring; inferred from name/signature.
  - `DataAccessLayer.update_training_cycle_state` (method, line 163): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_plan_muscle_volume` (method, line 176): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_actual_muscle_volume` (method, line 180): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_active_plan` (method, line 187): No docstring; inferred from name/signature.
  - `DataAccessLayer.get_plan_week` (method, line 191): No docstring; inferred from name/signature.
  - `DataAccessLayer.update_workout_targets` (method, line 195): No docstring; inferred from name/signature.
  - `DataAccessLayer.refresh_plan_view` (method, line 199): No docstring; inferred from name/signature.
  - `DataAccessLayer.refresh_actual_view` (method, line 203): No docstring; inferred from name/signature.
  - `DataAccessLayer.apply_plan_backoff` (method, line 207): No docstring; inferred from name/signature.
  - `DataAccessLayer.upsert_wger_categories` (method, line 220): No docstring; inferred from name/signature.
  - `DataAccessLayer.upsert_wger_equipment` (method, line 224): No docstring; inferred from name/signature.
  - `DataAccessLayer.upsert_wger_muscles` (method, line 228): No docstring; inferred from name/signature.
  - `DataAccessLayer.upsert_wger_exercises` (method, line 232): No docstring; inferred from name/signature.
  - `DataAccessLayer.save_validation_log` (method, line 239): No docstring; inferred from name/signature.
  - `DataAccessLayer.was_week_exported` (method, line 243): No docstring; inferred from name/signature.
  - `DataAccessLayer.record_wger_export` (method, line 247): No docstring; inferred from name/signature.

### `pete_e/domain/entities.py`
- **Module purpose (docstring):** Domain entities representing training plans and workouts.
- **Key imports:** __future__, dataclasses, datetime, pete_e.domain.configuration, pete_e.utils, statistics, typing
- **Top-level objects:**
  - `_metric_values` (function, line 15): No docstring; inferred from name/signature.
  - `Exercise` (class, line 29): Single exercise performed within a workout.
  - `Exercise.apply_progression` (method, line 40): Update the exercise's weight target based on progression rules.
  - `Workout` (class, line 124): A scheduled workout within a training week.
  - `Workout.is_weights_session` (method, line 140): No docstring; inferred from name/signature.
  - `Workout.apply_progression` (method, line 143): Apply progression to each exercise belonging to this workout.
  - `Workout.weight_target` (method, line 164): No docstring; inferred from name/signature.
  - `Week` (class, line 169): A training week containing multiple workouts.
  - `Week.weights_workouts` (method, line 176): No docstring; inferred from name/signature.
  - `Week.apply_progression` (method, line 181): Apply progression across all relevant workouts.
  - `Plan` (class, line 201): Structured training plan consisting of multiple weeks.
  - `Plan.muscle_totals` (method, line 208): No docstring; inferred from name/signature.
  - `compute_recovery_flag` (function, line 231): Return True when recovery markers are within the expected range.

### `pete_e/domain/french_trainer.py`
- **Module purpose (docstring):** Narrative generation in Pierre's franglais coach voice.
- **Key imports:** __future__, dataclasses, pete_e.domain, pete_e.utils, typing
- **Top-level objects:**
  - `Highlight` (class, line 18): No docstring; inferred from name/signature.
  - `_collect_records` (function, line 22): No docstring; inferred from name/signature.
  - `_score_metric` (function, line 41): No docstring; inferred from name/signature.
  - `_select_highlights` (function, line 64): No docstring; inferred from name/signature.
  - `_format_delta` (function, line 89): No docstring; inferred from name/signature.
  - `_record_suffix` (function, line 107): No docstring; inferred from name/signature.
  - `_build_weight_line` (function, line 123): No docstring; inferred from name/signature.
  - `_build_body_fat_line` (function, line 139): No docstring; inferred from name/signature.
  - `_build_muscle_line` (function, line 154): No docstring; inferred from name/signature.
  - `_build_rhr_line` (function, line 169): No docstring; inferred from name/signature.
  - `_build_steps_line` (function, line 189): No docstring; inferred from name/signature.
  - `_build_sleep_line` (function, line 204): No docstring; inferred from name/signature.
  - `_build_strength_line` (function, line 219): No docstring; inferred from name/signature.
  - `_build_squat_line` (function, line 234): No docstring; inferred from name/signature.
  - `_build_generic_line` (function, line 267): No docstring; inferred from name/signature.
  - `_format_highlight_paragraph` (function, line 282): No docstring; inferred from name/signature.
  - `_closing_phrase` (function, line 294): No docstring; inferred from name/signature.
  - `_today_session_message` (function, line 305): No docstring; inferred from name/signature.
  - `compose_daily_message` (function, line 316): No docstring; inferred from name/signature.

### `pete_e/domain/lift_log.py`
- **Key imports:** datetime, pete_e.domain.data_access, typing
- **Top-level objects:**
  - `append_log_entry` (function, line 10): Persist a strength training entry using the DAL.
  - `get_history_for_exercise` (function, line 32): Retrieves history for an exercise using the provided DAL. Includes set_number for clarity.

### `pete_e/domain/logging.py`
- **Module purpose (docstring):** Lightweight logging helpers for domain code without infrastructure coupling.
- **Key imports:** __future__, logging, typing
- **Top-level objects:**
  - `_resolve_level` (function, line 17): No docstring; inferred from name/signature.
  - `log_message` (function, line 23): Log ``message`` using the standard library logger.
  - `debug` (function, line 29): No docstring; inferred from name/signature.
  - `info` (function, line 33): No docstring; inferred from name/signature.
  - `warn` (function, line 37): No docstring; inferred from name/signature.
  - `error` (function, line 41): No docstring; inferred from name/signature.

### `pete_e/domain/metrics_service.py`
- **Module purpose (docstring):** Utility helpers for loading aggregated metrics for narratives.
- **Key imports:** __future__, datetime, pete_e.domain, pete_e.domain.data_access, pete_e.utils, typing
- **Top-level objects:**
  - `_window_values` (function, line 12): No docstring; inferred from name/signature.
  - `_average_window` (function, line 28): No docstring; inferred from name/signature.
  - `_extreme_window` (function, line 40): No docstring; inferred from name/signature.
  - `_build_metric_series` (function, line 53): No docstring; inferred from name/signature.
  - `_calculate_moving_averages` (function, line 73): No docstring; inferred from name/signature.
  - `_calculate_changes` (function, line 97): No docstring; inferred from name/signature.
  - `_find_historical_extremes` (function, line 127): No docstring; inferred from name/signature.
  - `_build_metric_stats` (function, line 155): No docstring; inferred from name/signature.
  - `get_metrics_overview` (function, line 222): Return derived metrics keyed by metric name using daily_summary history.

### `pete_e/domain/narrative_builder.py`
- Parse error: invalid non-printable character U+FEFF (<unknown>, line 1)

### `pete_e/domain/narrative_utils.py`
- **Key imports:** random
- **Top-level objects:**
  - `stitch_sentences` (function, line 92): Turn insights + sprinkles into a chatty Pete-style rant. If short_mode=True, or by random chance, just return a one-liner.

### `pete_e/domain/phrase_picker.py`
- **Key imports:** json, pathlib, pete_e.domain.configuration, pete_e.domain.logging, random
- **Top-level objects:**
  - `load_phrases` (function, line 14): Load phrases from JSON into memory (cached).
  - `random_phrase` (function, line 31): Pick a random phrase from Pete’s arsenal. kind: motivational, silly, portmanteau, metaphor, coachism, legendary, or any mode: serious | chaotic | balanced tags: optional list of ha…

### `pete_e/domain/plan_factory.py`
- **Module purpose (docstring):** Contains the business logic for constructing different types of training plans. This factory creates in-memory representations of plans, which are then persisted by an application service.
- **Key imports:** __future__, datetime, pete_e.domain, pete_e.domain.repositories, pete_e.domain.running_planner, random, typing
- **Top-level objects:**
  - `PlanFactory` (class, line 16): Creates structured, in-memory representations of training plans.
  - `PlanFactory.__init__` (method, line 19): Requires a PlanRepository to fetch necessary data like assistance pools and core exercise IDs.
  - `PlanFactory._pick_random` (method, line 27): Safely picks k random items from a list.
  - `PlanFactory._round_to_2p5` (method, line 34): Rounds a weight value to the nearest 2.5kg.
  - `PlanFactory._get_target_weight` (method, line 38): Calculates the target weight from a training max and percentage.
  - `PlanFactory._workout_sort_key` (method, line 50): No docstring; inferred from name/signature.
  - `PlanFactory.create_531_block_plan` (method, line 63): Builds a 4-week, 5/3/1 training block. Returns a structured dictionary representing the full plan, ready for persistence. (Logic migrated from plan_builder.py and orchestrator.py)
  - `PlanFactory.create_strength_test_plan` (method, line 185): Builds a 1-week AMRAP strength test plan. Returns a structured dictionary.

### `pete_e/domain/plan_mapper.py`
- **Module purpose (docstring):** Mapping utilities for converting plan payloads to domain entities.
- **Key imports:** __future__, dataclasses, pete_e.domain, pete_e.domain.entities, pete_e.utils, typing
- **Top-level objects:**
  - `PlanMapper` (class, line 14): Translate between persisted plan representations and domain entities.
  - `PlanMapper.to_entity` (method, line 17): No docstring; inferred from name/signature.
  - `PlanMapper.to_payload` (method, line 29): No docstring; inferred from name/signature.
  - `PlanMapper._extract_weeks` (method, line 71): No docstring; inferred from name/signature.
  - `PlanMapper._build_week` (method, line 80): No docstring; inferred from name/signature.
  - `PlanMapper._build_workout` (method, line 94): No docstring; inferred from name/signature.
  - `PlanMapper._build_exercise` (method, line 124): No docstring; inferred from name/signature.
  - `PlanMapper._to_int` (method, line 148): No docstring; inferred from name/signature.

### `pete_e/domain/progression.py`
- **Module purpose (docstring):** Adaptive weight progression logic operating on pre-fetched data.
- **Key imports:** dataclasses, pete_e.domain.entities, pete_e.utils, typing
- **Top-level objects:**
  - `_to_int` (function, line 16): No docstring; inferred from name/signature.
  - `WorkoutProgression` (class, line 38): Represents a single workout adjustment applied during calibration.
  - `PlanProgressionDecision` (class, line 49): Outcome of running progression for a specific plan week.
  - `_normalise_plan_week` (function, line 57): Convert raw plan rows into the structure expected by apply_progression.
  - `_compute_recovery_flag` (function, line 112): Compatibility wrapper delegating to the entity helper implementation.
  - `_adjust_exercise` (function, line 121): Proxy the historical helper API through the Exercise entity implementation.
  - `calibrate_plan_week` (function, line 159): Run progression for the specified plan week using supplied data.
  - `apply_progression` (function, line 213): Adjust weights based on lift log and recovery metrics.

### `pete_e/domain/repositories.py`
- **Key imports:** __future__, abc, typing
- **Top-level objects:**
  - `PlanRepository` (class, line 7): Abstract interface for plan-related persistence operations.
  - `PlanRepository.get_latest_training_maxes` (method, line 11): Return the latest recorded training max values by lift name.
  - `PlanRepository.save_full_plan` (method, line 15): Persist a plan and return its identifier.
  - `PlanRepository.get_assistance_pool_for` (method, line 19): Return IDs of assistance lifts associated with the given main lift.
  - `PlanRepository.get_core_pool_ids` (method, line 23): Return IDs of available core exercises.

### `pete_e/domain/running_planner.py`
- **Module purpose (docstring):** Running planning utilities. This module isolates running session construction from the strength plan builder so it can evolve toward adaptive, goal-driven planning.
- **Key imports:** __future__, dataclasses, datetime, pete_e.domain, pete_e.domain.validation, typing
- **Top-level objects:**
  - `RunningGoal` (class, line 18): Optional race goal inputs for future adaptive running logic.
  - `RunningLoadSummary` (class, line 28): Recent run-specific training load derived from Apple workout rows.
  - `RunningPlanProfile` (class, line 42): Plan shape chosen from running load, goal timing, and recovery metrics.
  - `MorningRunAdjustment` (class, line 58): Run-specific advice appended to the morning report when backing off.
  - `_coerce_date` (function, line 67): No docstring; inferred from name/signature.
  - `_coerce_float` (function, line 86): No docstring; inferred from name/signature.
  - `_normalise_runs` (function, line 95): No docstring; inferred from name/signature.
  - `summarise_running_load` (function, line 116): Summarise recent running volume without counting walking distance.
  - `_assess_recovery` (function, line 156): No docstring; inferred from name/signature.
  - `_phase_for_load` (function, line 170): No docstring; inferred from name/signature.
  - `_long_run_start_for_phase` (function, line 190): No docstring; inferred from name/signature.
  - `build_running_plan_profile` (function, line 201): Choose a conservative running block from current durability and recovery.
  - `_run_payload` (function, line 280): No docstring; inferred from name/signature.
  - `_progressed_long_run_distance` (function, line 302): No docstring; inferred from name/signature.
  - `_daily_load_backoff` (function, line 311): No docstring; inferred from name/signature.
  - `assess_morning_run_adjustment` (function, line 326): Return a run back-off instruction for the morning message, if needed.
  - `RunningPlanner` (class, line 380): Builds running sessions for each training week.
  - `RunningPlanner.build_week_sessions` (method, line 383): Return running workouts for a given week. ``goal`` and ``health_metrics`` are accepted now so the calling code can pass richer context as the adaptive planning rules are expanded.

### `pete_e/domain/schedule_rules.py`
- **Module purpose (docstring):** Centralised 5/3/1 scheduling parameters. This module defines the day split, set prescriptions, assistance pools, and any derived annotations (e.g. rest guidance) so the builders and export logic stay in lockstep with the published template.
- **Key imports:** __future__, datetime, typing
- **Top-level objects:**
  - `weight_slot_for_day` (function, line 72): Return the scheduled start time for weights on the given weekday (1..7).
  - `_normalise_week_number` (function, line 156): No docstring; inferred from name/signature.
  - `get_main_set_scheme` (function, line 160): Return the ordered set prescriptions for the requested week.
  - `main_set_summary` (function, line 167): Legacy accessor approximating the top set characteristics.
  - `rest_seconds_for` (function, line 180): Return the programmed rest interval for the supplied role.
  - `describe_main_set` (function, line 190): No docstring; inferred from name/signature.
  - `describe_assistance` (function, line 206): No docstring; inferred from name/signature.
  - `describe_core` (function, line 210): No docstring; inferred from name/signature.
  - `format_rest_seconds` (function, line 214): No docstring; inferred from name/signature.
  - `format_weight_kg` (function, line 225): No docstring; inferred from name/signature.
  - `workout_display_order` (function, line 235): Return the intended within-day ordering for a session.
  - `_clean_number_text` (function, line 263): No docstring; inferred from name/signature.
  - `_speed_range_text` (function, line 276): No docstring; inferred from name/signature.
  - `running_session_summary` (function, line 288): No docstring; inferred from name/signature.
  - `_stretch_step_label` (function, line 369): No docstring; inferred from name/signature.
  - `stretch_routine_summary` (function, line 386): No docstring; inferred from name/signature.
  - `stretch_routine_description` (function, line 426): No docstring; inferred from name/signature.
  - `build_export_comment` (function, line 451): No docstring; inferred from name/signature.
  - `default_assistance_for` (function, line 525): No docstring; inferred from name/signature.
  - `classify_exercise` (function, line 529): No docstring; inferred from name/signature.
  - `build_stretch_routine_details` (function, line 633): Return a copy of the configured stretch routine details.
  - `stretch_routine_for_day` (function, line 651): Return the stretch routine configured for a weekday, if any.
  - `_base_running_details` (function, line 684): No docstring; inferred from name/signature.
  - `quality_intervals_details` (function, line 695): No docstring; inferred from name/signature.
  - `quality_tempo_details` (function, line 712): No docstring; inferred from name/signature.
  - `easy_run_details` (function, line 722): No docstring; inferred from name/signature.
  - `steady_run_details` (function, line 742): No docstring; inferred from name/signature.
  - `recovery_micro_run_details` (function, line 762): No docstring; inferred from name/signature.
  - `long_run_details` (function, line 780): No docstring; inferred from name/signature.

### `pete_e/domain/scheduler.py`
- Parse error: invalid non-printable character U+FEFF (<unknown>, line 1)

### `pete_e/domain/token_storage.py`
- **Module purpose (docstring):** Domain-level protocol for persisting OAuth tokens.
- **Key imports:** __future__, typing
- **Top-level objects:**
  - `TokenStorage` (class, line 8): Abstraction for persisting OAuth token payloads.
  - `TokenStorage.read_tokens` (method, line 11): Return persisted tokens if available, otherwise ``None``.
  - `TokenStorage.save_tokens` (method, line 14): Persist the provided token payload.

### `pete_e/domain/user_helpers.py`
- **Key imports:** datetime, typing
- **Top-level objects:**
  - `calculate_age` (function, line 6): Calculates age based on a birth date, as of a specific date.

### `pete_e/domain/validation.py`
- **Key imports:** __future__, copy, dataclasses, datetime, pete_e.domain, pete_e.domain.configuration, pete_e.domain.entities, pete_e.utils, statistics, typing
- **Top-level objects:**
  - `_format_day_list` (function, line 45): No docstring; inferred from name/signature.
  - `WindowStats` (class, line 51): No docstring; inferred from name/signature.
  - `BaselineResult` (class, line 61): No docstring; inferred from name/signature.
  - `BackoffRecommendation` (class, line 67): No docstring; inferred from name/signature.
  - `ReadinessSummary` (class, line 76): No docstring; inferred from name/signature.
  - `ValidationDecision` (class, line 86): Outcome of plan validation ahead of Wger export or calibration.
  - `PlanContext` (class, line 99): Lightweight data container describing a persisted plan.
  - `MuscleBalanceReport` (class, line 107): No docstring; inferred from name/signature.
  - `collect_adherence_snapshot` (function, line 115): Return planned vs actual muscle volume coverage for the supplied window.
  - `_evaluate_adherence_adjustment` (function, line 198): No docstring; inferred from name/signature.
  - `ensure_muscle_balance` (function, line 283): No docstring; inferred from name/signature.
  - `validate_plan_structure` (function, line 314): Validate overall plan structure before persistence or export.
  - `_build_readiness_tip` (function, line 429): No docstring; inferred from name/signature.
  - `_build_readiness_summary` (function, line 445): No docstring; inferred from name/signature.
  - `_collect_series` (function, line 473): Extract a (date, value) series from historical rows.
  - `_detect_metric_key` (function, line 498): Return the first metric key present in rows from the candidate list.
  - `_slice_values_in_window` (function, line 513): Return values with start <= date <= end.
  - `_window_stats` (function, line 523): No docstring; inferred from name/signature.
  - `_weighted_baseline` (function, line 540): Combine medians across available windows using provided weights.
  - `_compute_baseline_for_metric` (function, line 556): Build a dynamic baseline for a metric using rolling windows. Uses medians per window, then a weighted blend favouring recency.
  - `_average_over_last_n_days` (function, line 579): Average of last N days up to 'end'. Returns None if insufficient points.
  - `_severity_from_breach_ratio` (function, line 596): Map a breach ratio to severity and recommended adjustments. ratio == 0 means within thresholds. 1.0 means exactly at threshold.
  - `_ensure_row_sequence` (function, line 610): Coerce historical rows into a list without assuming a backing store.
  - `compute_dynamic_baselines` (function, line 626): Compute dynamic baselines for RHR, Sleep, and (optionally) HRV as of 'reference_end_date'. The caller supplies historical metric rows covering the required window.
  - `assess_recovery_and_backoff` (function, line 669): Evaluate the prior week versus dynamic baselines and propose a global back-off. Observation window is the last 7 complete days ending the day before 'week_start_date'.
  - `summarise_readiness` (function, line 833): Return a non-destructive readiness summary for the supplied window.
  - `validate_and_adjust_plan` (function, line 841): Assess recovery ahead of the upcoming week and compute recommended adjustments.
  - `resolve_plan_context` (function, line 952): Normalise a plan record or DTO into a :class:`PlanContext`.

### `pete_e/infrastructure/apple_dropbox_client.py`
- Parse error: invalid non-printable character U+FEFF (<unknown>, line 1)

### `pete_e/infrastructure/apple_health_ingestor.py`
- **Module purpose (docstring):** Infrastructure implementation for importing Apple Health data.
- **Key imports:** __future__, dataclasses, datetime, io, json, pete_e.domain.daily_sync, pete_e.infrastructure, pete_e.infrastructure.apple_dropbox_client, pete_e.infrastructure.apple_parser, pete_e.infrastructure.apple_writer, pete_e.infrastructure.postgres_dal, typing ...
- **Top-level objects:**
  - `AppleIngestError` (class, line 25): Raised when the Apple Dropbox ingest encounters a recoverable failure.
  - `AppleIngestError.__post_init__` (method, line 32): No docstring; inferred from name/signature.
  - `AppleIngestError._compose_message` (method, line 35): No docstring; inferred from name/signature.
  - `AppleIngestError.__str__` (method, line 42): No docstring; inferred from name/signature.
  - `_get_json_from_content` (function, line 46): Extract JSON data from either a raw file or a zip archive.
  - `AppleHealthDropboxIngestor` (class, line 73): Import Apple Health exports stored in Dropbox into Postgres.
  - `AppleHealthDropboxIngestor.__init__` (method, line 76): No docstring; inferred from name/signature.
  - `AppleHealthDropboxIngestor.ingest` (method, line 89): No docstring; inferred from name/signature.
  - `AppleHealthDropboxIngestor.get_last_import_timestamp` (method, line 97): No docstring; inferred from name/signature.
  - `AppleHealthDropboxIngestor._run_ingest` (method, line 110): No docstring; inferred from name/signature.
  - `AppleHealthDropboxIngestor._download_file` (method, line 223): No docstring; inferred from name/signature.
  - `build_ingestor` (function, line 230): Convenience helper used by the DI container.

### `pete_e/infrastructure/apple_parser.py`
- **Key imports:** __future__, dataclasses, datetime, pete_e.infrastructure, re, typing
- **Top-level objects:**
  - `DailyMetricPoint` (class, line 35): No docstring; inferred from name/signature.
  - `DailyHeartRateSummary` (class, line 43): No docstring; inferred from name/signature.
  - `DailySleepSummary` (class, line 51): No docstring; inferred from name/signature.
  - `WorkoutHeader` (class, line 65): No docstring; inferred from name/signature.
  - `WorkoutHRPoint` (class, line 81): No docstring; inferred from name/signature.
  - `WorkoutStepsPoint` (class, line 89): No docstring; inferred from name/signature.
  - `WorkoutEnergyPoint` (class, line 95): No docstring; inferred from name/signature.
  - `WorkoutHRRecoveryPoint` (class, line 101): No docstring; inferred from name/signature.
  - `AppleHealthParser` (class, line 109): Parse a HealthAutoExport JSON document into domain rows for persistence.
  - `AppleHealthParser._parse_dt` (method, line 113): No docstring; inferred from name/signature.
  - `AppleHealthParser._canon_metric_name` (method, line 119): No docstring; inferred from name/signature.
  - `AppleHealthParser._get_numeric_value` (method, line 123): Safely extracts a float from numbers, strings, or nested dict structures.
  - `AppleHealthParser._extract_unit` (method, line 164): No docstring; inferred from name/signature.
  - `AppleHealthParser._extract_measure` (method, line 192): No docstring; inferred from name/signature.
  - `AppleHealthParser._normalise_temperature` (method, line 200): No docstring; inferred from name/signature.
  - `AppleHealthParser._normalise_humidity` (method, line 209): No docstring; inferred from name/signature.
  - `AppleHealthParser._extract_workout_environment` (method, line 221): No docstring; inferred from name/signature.
  - `AppleHealthParser.parse` (method, line 288): Parse root HealthAutoExport JSON into typed streams for persistence.

### `pete_e/infrastructure/apple_writer.py`
- **Key imports:** dataclasses, datetime, pete_e.config.config, pete_e.infrastructure, pete_e.infrastructure.apple_parser, psycopg, typing
- **Top-level objects:**
  - `AppleHealthWriter` (class, line 25): Persists parsed Apple Health data into Postgres using efficient bulk upserts.
  - `AppleHealthWriter.__init__` (method, line 28): No docstring; inferred from name/signature.
  - `AppleHealthWriter._ensure_ids_cached` (method, line 34): Efficiently pre-fetches all required device and type IDs.
  - `AppleHealthWriter._ensure_ref_item` (method, line 55): Generic helper to find or create a reference item (e.g., Device, MetricType).
  - `AppleHealthWriter.get_last_import_timestamp` (method, line 82): Retrieves the timestamp of the most recently processed file from the ImportLog. Returns None if no imports have occurred yet. The returned datetime is guaranteed to be timezone-awa…
  - `AppleHealthWriter.save_last_import_timestamp` (method, line 105): Saves a record of this import run, logging the timestamp of the newest file.
  - `AppleHealthWriter._execute_many_upsert` (method, line 114): A generic, high-performance bulk upsert function.
  - `AppleHealthWriter._prepare_data_for_bulk_upsert` (method, line 149): Pre-fetches all foreign key IDs to avoid row-by-row lookups.
  - `AppleHealthWriter._utc_to_naive` (method, line 166): Safely converts a timezone-aware datetime to a naive UTC datetime.
  - `AppleHealthWriter.upsert_all` (method, line 172): Main entrypoint to upsert all parsed data in efficient batches.

### `pete_e/infrastructure/cron_manager.py`
- **Key imports:** argparse, csv, datetime, pathlib, subprocess, sys
- **Top-level objects:**
  - `_is_comment_row` (function, line 14): No docstring; inferred from name/signature.
  - `_is_enabled_row` (function, line 19): No docstring; inferred from name/signature.
  - `build_crontab_from_csv` (function, line 23): Convert CSV schedule into crontab text, or None if missing.
  - `save_crontab_file` (function, line 44): No docstring; inferred from name/signature.
  - `backup_existing_crontab` (function, line 54): No docstring; inferred from name/signature.
  - `activate_crontab` (function, line 63): No docstring; inferred from name/signature.
  - `print_summary` (function, line 74): No docstring; inferred from name/signature.
  - `main` (function, line 110): No docstring; inferred from name/signature.

### `pete_e/infrastructure/db_conn.py`
- **Module purpose (docstring):** Utility helpers for database connection configuration.
- **Key imports:** __future__, pete_e.config
- **Top-level objects:**
  - `get_database_url` (function, line 8): Return the configured PostgreSQL connection URL. Preference is given to the ``DATABASE_URL`` environment variable so that command invocations can override configuration at runtime.…

### `pete_e/infrastructure/decorators.py`
- **Module purpose (docstring):** Infrastructure-level decorators used across API clients.
- **Key imports:** __future__, functools, pete_e.infrastructure, time, typing
- **Top-level objects:**
  - `retry_on_network_error` (function, line 14): Retry decorator with exponential backoff for transient failures. Parameters ---------- should_retry: Callable that accepts ``self`` and an HTTP status code, returning ``True`` when…
  - `_extract_arg` (function, line 85): Helper to extract positional/keyword arguments for logging.

### `pete_e/infrastructure/di_container.py`
- **Module purpose (docstring):** Dependency injection container for Pete-E services.
- **Key imports:** __future__, functools, inspect, pete_e.application.services, pete_e.config, pete_e.domain.configuration, pete_e.domain.daily_sync, pete_e.infrastructure.apple_dropbox_client, pete_e.infrastructure.apple_health_ingestor, pete_e.infrastructure.postgres_dal, pete_e.infrastructure.telegram_client, pete_e.infrastructure.token_storage ...
- **Top-level objects:**
  - `Container` (class, line 40): Minimal service container supporting factories and instances.
  - `Container.__init__` (method, line 43): No docstring; inferred from name/signature.
  - `Container.register` (method, line 47): No docstring; inferred from name/signature.
  - `Container.resolve` (method, line 63): No docstring; inferred from name/signature.
  - `_register_defaults` (function, line 73): Register the production service graph with the container.
  - `_wrap_override` (function, line 108): No docstring; inferred from name/signature.
  - `build_container` (function, line 119): Create a new container with optional dependency overrides.
  - `get_container` (function, line 136): Return a cached container instance for application use.

### `pete_e/infrastructure/git_utils.py`
- **Key imports:** datetime, subprocess
- **Top-level objects:**
  - `commit_changes` (function, line 6): Stage all changes and commit to git.

### `pete_e/infrastructure/log_utils.py`
- **Module purpose (docstring):** Utility helpers for writing Pete's logs with rotation and tagging support.
- **Key imports:** __future__, inspect, logging, pete_e.logging_setup, typing
- **Top-level objects:**
  - `log_message` (function, line 21): Log a message to Pete's rotating history log with optional tagging. Accepts **kwargs for compatibility with standard logging arguments like exc_info=True, stacklevel=2, etc.
  - `debug` (function, line 55): No docstring; inferred from name/signature.
  - `info` (function, line 59): No docstring; inferred from name/signature.
  - `warn` (function, line 63): No docstring; inferred from name/signature.
  - `error` (function, line 67): No docstring; inferred from name/signature.
  - `critical` (function, line 71): No docstring; inferred from name/signature.

### `pete_e/infrastructure/mappers/__init__.py`
- **Module purpose (docstring):** Infrastructure mappers bridging persistence and domain layers.
- **Key imports:** plan_mapper, wger_mapper
- **Top-level objects:** none

### `pete_e/infrastructure/mappers/plan_mapper.py`
- **Module purpose (docstring):** Mapping utilities for converting between persistence rows and domain plans.
- **Key imports:** __future__, dataclasses, datetime, pete_e.domain, pete_e.domain.entities, pete_e.utils, typing
- **Top-level objects:**
  - `PlanMappingError` (class, line 14): Raised when a persistence payload cannot be converted to a Plan.
  - `PlanMapper` (class, line 19): Translate between persistence-layer representations and ``Plan`` objects.
  - `PlanMapper.from_rows` (method, line 22): Build a :class:`Plan` from database rows.
  - `PlanMapper.from_dict` (method, line 58): Construct a :class:`Plan` from the plan dictionaries used by the DAL.
  - `PlanMapper.to_persistence_payload` (method, line 76): Convert a domain :class:`Plan` into the structure expected by the DAL.
  - `PlanMapper._build_week` (method, line 105): No docstring; inferred from name/signature.
  - `PlanMapper._build_workout` (method, line 122): No docstring; inferred from name/signature.
  - `PlanMapper._build_exercise` (method, line 165): No docstring; inferred from name/signature.
  - `PlanMapper._iter_week_payloads` (method, line 208): No docstring; inferred from name/signature.
  - `PlanMapper._workout_to_payload` (method, line 219): No docstring; inferred from name/signature.
  - `PlanMapper._to_int` (method, line 251): No docstring; inferred from name/signature.
  - `PlanMapper._to_date` (method, line 273): No docstring; inferred from name/signature.
  - `PlanMapper._to_time_string` (method, line 276): No docstring; inferred from name/signature.
  - `PlanMapper._validate_metadata` (method, line 290): No docstring; inferred from name/signature.

### `pete_e/infrastructure/mappers/wger_mapper.py`
- **Module purpose (docstring):** Mapping utilities for converting domain plans to wger payloads.
- **Key imports:** __future__, dataclasses, datetime, pete_e.domain, pete_e.domain.entities, typing
- **Top-level objects:**
  - `WgerMappingError` (class, line 13): Raised when a domain plan cannot be converted into an API payload.
  - `WgerPayloadMapper` (class, line 18): Create payloads understood by the wger API.
  - `WgerPayloadMapper.build_week_payload` (method, line 21): Return a payload describing the workouts for ``week_number``.
  - `WgerPayloadMapper.build_plan_payload` (method, line 66): Return a payload for all weeks in ``plan``.
  - `WgerPayloadMapper._find_week` (method, line 79): No docstring; inferred from name/signature.
  - `WgerPayloadMapper._workout_to_payload` (method, line 85): No docstring; inferred from name/signature.

### `pete_e/infrastructure/postgres_dal.py`
- **Module purpose (docstring):** The single, consolidated Data Access Layer for all PostgreSQL interactions. This class implements the DataAccessLayer interface and handles all database reads, writes, and catalog management.
- **Key imports:** __future__, contextlib, datetime, hashlib, json, pete_e.config, pete_e.domain, pete_e.domain.repositories, pete_e.domain.validation, pete_e.infrastructure, pete_e.infrastructure.db_conn, psycopg ...
- **Top-level objects:**
  - `_create_pool` (function, line 30): No docstring; inferred from name/signature.
  - `get_pool` (function, line 34): No docstring; inferred from name/signature.
  - `PostgresDal` (class, line 41): PostgreSQL implementation of the Data Access Layer.
  - `PostgresDal.__init__` (method, line 44): No docstring; inferred from name/signature.
  - `PostgresDal._get_cursor` (method, line 48): No docstring; inferred from name/signature.
  - `PostgresDal.connection` (method, line 57): Provide a context manager for a pooled database connection.
  - `PostgresDal.close` (method, line 61): No docstring; inferred from name/signature.
  - `PostgresDal._ensure_single_active_plan_invariant` (method, line 67): No docstring; inferred from name/signature.
  - `PostgresDal._core_pool_table_exists` (method, line 93): No docstring; inferred from name/signature.
  - `PostgresDal.hold_plan_generation_lock` (method, line 101): Serialize plan generation and export across processes.
  - `PostgresDal.save_full_plan` (method, line 122): No docstring; inferred from name/signature.
  - `PostgresDal.get_assistance_pool_for` (method, line 264): No docstring; inferred from name/signature.
  - `PostgresDal.get_core_pool_ids` (method, line 273): No docstring; inferred from name/signature.
  - `PostgresDal.create_block_and_plan` (method, line 295): No docstring; inferred from name/signature.
  - `PostgresDal.insert_workout` (method, line 314): No docstring; inferred from name/signature.
  - `PostgresDal.get_active_plan` (method, line 319): No docstring; inferred from name/signature.
  - `PostgresDal.get_plan_week_rows` (method, line 325): No docstring; inferred from name/signature.
  - `PostgresDal.get_plan_week` (method, line 350): Compatibility wrapper for callers expecting the legacy DAL name.
  - `PostgresDal.get_plan_for_day` (method, line 354): No docstring; inferred from name/signature.
  - `PostgresDal.get_plan_for_week` (method, line 357): No docstring; inferred from name/signature.
  - `PostgresDal.get_week_ids_for_plan` (method, line 360): No docstring; inferred from name/signature.
  - `PostgresDal.find_plan_by_start_date` (method, line 369): No docstring; inferred from name/signature.
  - `PostgresDal.has_any_plan` (method, line 375): No docstring; inferred from name/signature.
  - `PostgresDal.update_workout_targets` (method, line 381): No docstring; inferred from name/signature.
  - `PostgresDal.apply_plan_backoff` (method, line 397): No docstring; inferred from name/signature.
  - `PostgresDal.create_test_week_plan` (method, line 451): No docstring; inferred from name/signature.
  - `PostgresDal.get_latest_test_week` (method, line 468): No docstring; inferred from name/signature.
  - `PostgresDal.insert_strength_test_result` (method, line 474): No docstring; inferred from name/signature.
  - `PostgresDal.upsert_training_max` (method, line 479): No docstring; inferred from name/signature.
  - `PostgresDal.get_latest_training_maxes` (method, line 484): No docstring; inferred from name/signature.
  - `PostgresDal.get_latest_training_max_date` (method, line 493): No docstring; inferred from name/signature.
  - `PostgresDal.save_withings_daily` (method, line 506): No docstring; inferred from name/signature.
  - `PostgresDal._epoch_to_timestamp` (method, line 579): No docstring; inferred from name/signature.
  - `PostgresDal.save_withings_measure_groups` (method, line 587): No docstring; inferred from name/signature.
  - `PostgresDal.save_wger_log` (method, line 660): No docstring; inferred from name/signature.
  - `PostgresDal.load_lift_log` (method, line 665): No docstring; inferred from name/signature.
  - `PostgresDal._bulk_upsert` (method, line 686): No docstring; inferred from name/signature.
  - `PostgresDal.upsert_wger_exercises_and_relations` (method, line 698): No docstring; inferred from name/signature.
  - `PostgresDal.seed_main_lifts_and_assistance` (method, line 746): No docstring; inferred from name/signature.
  - `PostgresDal.get_daily_summary` (method, line 758): Return the daily_summary row for a specific date.
  - `PostgresDal.get_historical_data` (method, line 772): No docstring; inferred from name/signature.
  - `PostgresDal.get_data_for_validation` (method, line 778): Return all historical, planned, and actual data required for validation.
  - `PostgresDal.get_historical_metrics` (method, line 922): No docstring; inferred from name/signature.
  - `PostgresDal.get_recent_running_workouts` (method, line 928): Return recent Apple workouts that are explicitly running sessions.
  - `PostgresDal.get_recent_strength_workouts` (method, line 977): Return recent strength logs grouped by day and exercise.
  - `PostgresDal.get_metrics_overview` (method, line 1007): No docstring; inferred from name/signature.
  - `PostgresDal.refresh_daily_summary` (method, line 1010): No docstring; inferred from name/signature.
  - `PostgresDal.get_plan_muscle_volume` (method, line 1021): No docstring; inferred from name/signature.
  - `PostgresDal.get_actual_muscle_volume` (method, line 1027): No docstring; inferred from name/signature.
  - `PostgresDal.refresh_plan_view` (method, line 1033): No docstring; inferred from name/signature.
  - `PostgresDal.refresh_actual_view` (method, line 1037): No docstring; inferred from name/signature.
  - `PostgresDal.was_week_exported` (method, line 1044): No docstring; inferred from name/signature.
  - `PostgresDal.record_wger_export` (method, line 1050): No docstring; inferred from name/signature.
  - `PostgresDal.save_validation_log` (method, line 1057): No docstring; inferred from name/signature.
  - `PostgresDal._call_function` (method, line 1060): Execute a SQL function and return column names and rows.

### `pete_e/infrastructure/telegram_client.py`
- **Module purpose (docstring):** Telegram Bot API client implementation.
- **Key imports:** __future__, pete_e.config, pete_e.infrastructure, requests, typing
- **Top-level objects:**
  - `_secret_to_str` (function, line 15): Best-effort extraction of raw secret string values.
  - `_scrub_sensitive` (function, line 29): Redacts known Telegram credentials from the outgoing message.
  - `TelegramClient` (class, line 48): Client responsible for interacting with the Telegram Bot API.
  - `TelegramClient.__init__` (method, line 51): No docstring; inferred from name/signature.
  - `TelegramClient._resolve_token` (method, line 64): No docstring; inferred from name/signature.
  - `TelegramClient._resolve_chat_id` (method, line 67): No docstring; inferred from name/signature.
  - `TelegramClient._scrub` (method, line 70): No docstring; inferred from name/signature.
  - `TelegramClient.ping` (method, line 79): Confirm Telegram bot reachability without sending a message.
  - `TelegramClient.send_message` (method, line 119): Send a message to the configured Telegram chat.
  - `TelegramClient.get_updates` (method, line 162): Poll Telegram for new updates using the configured bot credentials.
  - `TelegramClient.send_alert` (method, line 213): Send a high-priority alert via Telegram, redacting secrets first.

### `pete_e/infrastructure/telegram_sender.py`
- **Module purpose (docstring):** High-level helpers built on top of the Telegram client.
- **Key imports:** __future__, pete_e.infrastructure.di_container, pete_e.infrastructure.telegram_client
- **Top-level objects:**
  - `_get_client` (function, line 9): No docstring; inferred from name/signature.
  - `send_message` (function, line 15): Send a message to Telegram using the shared client.
  - `get_updates` (function, line 21): Fetch Telegram updates via the shared client.
  - `send_alert` (function, line 33): Send a high-priority Telegram alert using the shared client.

### `pete_e/infrastructure/token_storage.py`
- **Module purpose (docstring):** Infrastructure implementations of token persistence.
- **Key imports:** __future__, json, os, pathlib, pete_e.domain.token_storage, pete_e.infrastructure.log_utils, typing
- **Top-level objects:**
  - `JsonFileTokenStorage` (class, line 14): Persist tokens to a JSON file on disk.
  - `JsonFileTokenStorage.__init__` (method, line 17): No docstring; inferred from name/signature.
  - `JsonFileTokenStorage.read_tokens` (method, line 20): No docstring; inferred from name/signature.
  - `JsonFileTokenStorage.save_tokens` (method, line 30): No docstring; inferred from name/signature.

### `pete_e/infrastructure/wger_client.py`
- **Module purpose (docstring):** A unified client for all read and write interactions with the wger API v2. This module consolidates logic from the previous implementations while offering both API key and username/password authentication flows.
- **Key imports:** __future__, datetime, pete_e.config, pete_e.infrastructure, pete_e.infrastructure.decorators, requests, typing, urllib.parse
- **Top-level objects:**
  - `_unwrap_secret` (function, line 19): Return the plain value for SecretStr instances.
  - `WgerError` (class, line 29): Custom exception for Wger API errors.
  - `WgerError.__init__` (method, line 32): No docstring; inferred from name/signature.
  - `WgerClient` (class, line 39): No docstring; inferred from name/signature.
  - `WgerClient.__init__` (method, line 43): No docstring; inferred from name/signature.
  - `WgerClient._get_jwt_token` (method, line 71): No docstring; inferred from name/signature.
  - `WgerClient._headers` (method, line 91): No docstring; inferred from name/signature.
  - `WgerClient._url` (method, line 108): No docstring; inferred from name/signature.
  - `WgerClient._should_retry` (method, line 115): No docstring; inferred from name/signature.
  - `WgerClient._request` (method, line 119): Internal request handler with retry logic.
  - `WgerClient.ping` (method, line 147): Confirm authenticated connectivity to the wger API.
  - `WgerClient.get_all_pages` (method, line 157): Fetches and aggregates results from all pages of a paginated endpoint.
  - `WgerClient.find_exercise_translation` (method, line 181): No docstring; inferred from name/signature.
  - `WgerClient.ensure_custom_exercise` (method, line 205): No docstring; inferred from name/signature.
  - `WgerClient.get_workout_logs` (method, line 257): Fetches workout logs within a date range.
  - `WgerClient.find_or_create_routine` (method, line 268): Finds a routine by name and start date, creating it if it doesn't exist.
  - `WgerClient.delete_all_days_in_routine` (method, line 278): Wipes all Day objects associated with a routine.
  - `WgerClient.create_day` (method, line 293): No docstring; inferred from name/signature.
  - `WgerClient.create_slot` (method, line 297): No docstring; inferred from name/signature.
  - `WgerClient.create_slot_entry` (method, line 301): No docstring; inferred from name/signature.
  - `WgerClient.set_config` (method, line 317): Generic method to post to sets-config, repetitions-config, etc.

### `pete_e/infrastructure/withings_client.py`
- Parse error: invalid non-printable character U+FEFF (<unknown>, line 1)

### `pete_e/infrastructure/withings_oauth_helper.py`
- **Key imports:** json, os, pathlib, pete_e.config, pete_e.infrastructure.log_utils, pydantic, requests, urllib.parse
- **Top-level objects:**
  - `_unwrap_secret` (function, line 14): No docstring; inferred from name/signature.
  - `build_authorize_url` (function, line 24): No docstring; inferred from name/signature.
  - `exchange_code_for_tokens` (function, line 34): No docstring; inferred from name/signature.

### `pete_e/logging_setup.py`
- **Module purpose (docstring):** Central logging configuration for Pete-Eebot.
- **Key imports:** __future__, inspect, logging, logging.handlers, pathlib, pete_e.config, sys, time, typing
- **Top-level objects:**
  - `TaggedLogger` (class, line 23): Logger adapter that injects a tag field for structured Pete logs.
  - `TaggedLogger.process` (method, line 26): No docstring; inferred from name/signature.
  - `_resolve_level` (function, line 35): Translate a textual level into the numeric value logging expects.
  - `_build_formatter` (function, line 50): No docstring; inferred from name/signature.
  - `configure_logging` (function, line 59): Ensure the shared logger has a rotating file handler configured.
  - `get_logger` (function, line 131): Return a tagged Pete logger, configuring it on first access.
  - `get_tag_for_module` (function, line 161): Infer a logging tag from the script or module name.
  - `reset_logging` (function, line 169): Tear down handlers so tests can reconfigure the logger cleanly.

### `pete_e/utils/__init__.py`
- **Module purpose (docstring):** Shared utility helpers for Pete-E.
- **Key imports:** 
- **Top-level objects:** none

### `pete_e/utils/converters.py`
- **Module purpose (docstring):** Type conversion helpers used across the Pete-E codebase.
- **Key imports:** __future__, datetime, decimal, typing
- **Top-level objects:**
  - `to_float` (function, line 10): Safely convert ``value`` to ``float`` where possible.
  - `to_date` (function, line 33): Best-effort conversion of common date representations to ``date``.
  - `minutes_to_hours` (function, line 51): Convert a minutes value into hours when possible.

### `pete_e/utils/formatters.py`
- **Module purpose (docstring):** Text formatting helpers.
- **Key imports:** __future__
- **Top-level objects:**
  - `ensure_sentence` (function, line 6): Ensure ``text`` ends with a sentence terminator when non-empty.

### `pete_e/utils/helpers.py`
- **Module purpose (docstring):** General helper utilities shared across Pete-E.
- **Key imports:** __future__, random, typing
- **Top-level objects:**
  - `choose_from` (function, line 9): Return a random element from ``options`` or ``default`` when empty.

### `pete_e/utils/math.py`
- **Module purpose (docstring):** Numeric helpers shared across Pete-E modules.
- **Key imports:** __future__, typing
- **Top-level objects:**
  - `average` (function, line 8): Compute the mean of ``values`` while skipping ``None`` entries.
  - `mean_or_none` (function, line 17): Return the arithmetic mean of ``values`` or ``None`` when empty.
  - `near` (function, line 26): Return ``True`` when ``value`` is within ``tolerance`` of ``target``.

### `scripts/check_auth.py`
- Parse error: invalid non-printable character U+FEFF (<unknown>, line 1)

### `scripts/generate_plan.py`
- **Module purpose (docstring):** CLI entrypoint for generating a plan and exporting it to wger.
- **Key imports:** argparse, datetime, pete_e.application.plan_generation
- **Top-level objects:**
  - `main` (function, line 10): No docstring; inferred from name/signature.

### `scripts/heartbeat_check.py`
- **Module purpose (docstring):** Pete-Eebot Heartbeat Check Purpose: - Runs every 10 minutes via cron. - Logs a simple heartbeat. - Ensures pete_eebot.service is running; restarts it if not. - Sends a Telegram alert if a restart is needed.
- **Key imports:** pete_e.infrastructure, pete_e.logging_setup, subprocess
- **Top-level objects:**
  - `check_service` (function, line 19): Check if a systemd service is active.
  - `restart_service` (function, line 30): Try to restart a systemd service.
  - `send_telegram_alert` (function, line 42): Send an alert message via Telegram.
  - `main` (function, line 50): No docstring; inferred from name/signature.

### `scripts/inspect_withings_response.py`
- **Module purpose (docstring):** Fetch and print the raw Withings measure payload for inspection. Examples: python -m scripts.inspect_withings_response --days-back 0 --show-types python -m scripts.inspect_withings_response --start-date 2026-04-13 --end-date 2026-04-14 python -m scripts.inspect_withings_response --days-back 0 --latest-group-only --output withings_latest.json
- **Key imports:** __future__, argparse, datetime, json, pathlib, pete_e.infrastructure.token_storage, pete_e.infrastructure.withings_client, requests, typing
- **Top-level objects:**
  - `_EnvRefreshTokenBootstrapStorage` (class, line 39): Ignore stale persisted tokens once, but save fresh tokens normally.
  - `_EnvRefreshTokenBootstrapStorage.__init__` (method, line 42): No docstring; inferred from name/signature.
  - `_EnvRefreshTokenBootstrapStorage.read_tokens` (method, line 45): No docstring; inferred from name/signature.
  - `_EnvRefreshTokenBootstrapStorage.save_tokens` (method, line 48): No docstring; inferred from name/signature.
  - `_parse_iso_date` (function, line 52): No docstring; inferred from name/signature.
  - `_resolve_window` (function, line 59): No docstring; inferred from name/signature.
  - `_fetch_payload` (function, line 82): No docstring; inferred from name/signature.
  - `_trim_to_latest_group` (function, line 113): No docstring; inferred from name/signature.
  - `_measure_type_counts` (function, line 136): No docstring; inferred from name/signature.
  - `_measure_type_summary` (function, line 161): No docstring; inferred from name/signature.
  - `main` (function, line 179): No docstring; inferred from name/signature.

### `scripts/run_sunday_review.py`
- **Module purpose (docstring):** Executes the main Sunday review, handling weekly calibration and cycle rollover.
- **Key imports:** pete_e.application.orchestrator, pete_e.infrastructure
- **Top-level objects:**
  - `main` (function, line 8): Runs the weekly end-to-end automation.

### `scripts/send_telegram_message.py`
- **Module purpose (docstring):** A simple, standalone script to send a message to a Telegram chat. This script is designed to be called from automation, like the deploy.sh script. It loads environment variables directly from the project's .env file, constructs a message, and sends it using a direct HTTP request. This avoids depending on the full application stack (Typer, DI container, etc.) for a simple notification task, making it more robust. Usage: python scripts/send_telegram_message.py "Your message here"
- **Key imports:** argparse, dotenv, os, pathlib, requests, sys
- **Top-level objects:**
  - `main` (function, line 22): Parses arguments, loads environment, and sends the Telegram message.

### `scripts/sync_wger_catalog.py`
- **Module purpose (docstring):** CLI entrypoint for refreshing the local wger catalog.
- **Key imports:** pete_e.application.catalog_sync
- **Top-level objects:**
  - `main` (function, line 7): No docstring; inferred from name/signature.

### `scripts/weekly_calibration.py`
- **Module purpose (docstring):** Backward-compatible weekly automation entry point.
- **Key imports:** scripts.run_sunday_review
- **Top-level objects:** none

### `tests/api/test_api_services.py`
- **Key imports:** asyncio, hashlib, hmac, pete_e, pytest, sys, types, unittest.mock
- **Top-level objects:**
  - `request_stub` (function, line 64): No docstring; inferred from name/signature.
  - `enable_api_key` (function, line 69): No docstring; inferred from name/signature.
  - `test_metrics_overview_uses_service` (function, line 73): No docstring; inferred from name/signature.
  - `test_coach_state_uses_service` (function, line 86): No docstring; inferred from name/signature.
  - `test_recent_workouts_uses_service` (function, line 99): No docstring; inferred from name/signature.
  - `test_plan_for_day_uses_service` (function, line 117): No docstring; inferred from name/signature.
  - `test_plan_for_week_uses_service` (function, line 130): No docstring; inferred from name/signature.
  - `test_status_requires_api_key_configuration` (function, line 143): No docstring; inferred from name/signature.
  - `test_github_webhook_uses_configured_secret_and_deploy_path` (function, line 152): No docstring; inferred from name/signature.
  - `test_api_module_has_no_psycopg_import` (function, line 177): No docstring; inferred from name/signature.

### `tests/application/test_application_plan_service.py`
- **Key imports:** datetime, pete_e.application.exceptions, pete_e.application.plan_context_service, pete_e.domain.validation, pytest, tests.config_stub, typing
- **Top-level objects:**
  - `StubDal` (class, line 13): No docstring; inferred from name/signature.
  - `StubDal.__init__` (method, line 14): No docstring; inferred from name/signature.
  - `StubDal.get_active_plan` (method, line 28): No docstring; inferred from name/signature.
  - `StubDal.find_plan_by_start_date` (method, line 33): No docstring; inferred from name/signature.
  - `test_returns_context_from_active_plan` (function, line 40): No docstring; inferred from name/signature.
  - `test_falls_back_to_lookup_by_week_start` (function, line 50): No docstring; inferred from name/signature.
  - `test_returns_none_when_no_plan_available` (function, line 61): No docstring; inferred from name/signature.
  - `test_raises_data_access_error_when_dal_fails` (function, line 70): No docstring; inferred from name/signature.

### `tests/application/test_coach_api_service.py`
- **Key imports:** __future__, datetime, pete_e.application.api_services
- **Top-level objects:**
  - `CoachDal` (class, line 8): No docstring; inferred from name/signature.
  - `CoachDal.__init__` (method, line 9): No docstring; inferred from name/signature.
  - `CoachDal.get_metrics_overview` (method, line 12): No docstring; inferred from name/signature.
  - `CoachDal.get_daily_summary` (method, line 15): No docstring; inferred from name/signature.
  - `CoachDal.get_historical_data` (method, line 26): No docstring; inferred from name/signature.
  - `CoachDal.get_recent_running_workouts` (method, line 43): No docstring; inferred from name/signature.
  - `CoachDal.get_recent_strength_workouts` (method, line 54): No docstring; inferred from name/signature.
  - `CoachDal.get_active_plan` (method, line 65): No docstring; inferred from name/signature.
  - `CoachDal.get_latest_training_maxes` (method, line 68): No docstring; inferred from name/signature.
  - `CoachDal.get_latest_training_max_date` (method, line 71): No docstring; inferred from name/signature.
  - `test_daily_summary_adds_units_sources_and_quality` (function, line 75): No docstring; inferred from name/signature.
  - `test_coach_state_exposes_derived_flags_and_context` (function, line 84): No docstring; inferred from name/signature.

### `tests/application/test_export.py`
- **Key imports:** __future__, datetime, pete_e.application.orchestrator, pete_e.application.services, pete_e.domain, pete_e.domain.validation, pytest, tests.di_utils, types, unittest.mock
- **Top-level objects:**
  - `_make_validation_decision` (function, line 20): No docstring; inferred from name/signature.
  - `test_export_plan_week_uses_cached_validation` (function, line 46): No docstring; inferred from name/signature.
  - `test_export_plan_week_uses_fallback_routine_when_cleanup_fails` (function, line 87): No docstring; inferred from name/signature.
  - `test_export_plan_week_labels_test_week_main_lifts_as_amrap` (function, line 147): No docstring; inferred from name/signature.
  - `test_export_plan_week_posts_weight_config_for_target_loads` (function, line 202): No docstring; inferred from name/signature.
  - `test_export_plan_week_orders_sessions_and_creates_visible_limber_11` (function, line 302): No docstring; inferred from name/signature.
  - `test_build_payload_expands_stretch_routines_when_enabled` (function, line 454): No docstring; inferred from name/signature.
  - `test_export_plan_week_warns_when_main_lift_has_no_target_weight` (function, line 494): No docstring; inferred from name/signature.
  - `test_run_end_to_end_week_passes_cached_validation` (function, line 566): No docstring; inferred from name/signature.

### `tests/application/test_orchestrator_exceptions.py`
- **Key imports:** __future__, datetime, pete_e.application.exceptions, pete_e.application.orchestrator, pytest, tests.di_utils, types
- **Top-level objects:**
  - `StubDal` (class, line 13): No docstring; inferred from name/signature.
  - `StubDal.__init__` (method, line 14): No docstring; inferred from name/signature.
  - `StubDal.get_active_plan` (method, line 18): No docstring; inferred from name/signature.
  - `StubDal.close` (method, line 23): No docstring; inferred from name/signature.
  - `ExplodingValidationService` (class, line 27): No docstring; inferred from name/signature.
  - `ExplodingValidationService.validate_and_adjust_plan` (method, line 28): No docstring; inferred from name/signature.
  - `ExplodingCycleService` (class, line 32): No docstring; inferred from name/signature.
  - `ExplodingCycleService.check_and_rollover` (method, line 33): No docstring; inferred from name/signature.
  - `_make_orchestrator` (function, line 37): No docstring; inferred from name/signature.
  - `test_run_weekly_calibration_raises_validation_error` (function, line 61): No docstring; inferred from name/signature.
  - `test_run_cycle_rollover_wraps_export_errors` (function, line 77): No docstring; inferred from name/signature.
  - `test_run_end_to_end_week_raises_for_dal_failures` (function, line 98): No docstring; inferred from name/signature.
  - `test_run_end_to_end_week_raises_for_cycle_failures` (function, line 122): No docstring; inferred from name/signature.

### `tests/application/test_orchestrator_messages.py`
- **Key imports:** __future__, datetime, pete_e.application.orchestrator, pete_e.infrastructure.telegram_client, pytest, tests, tests.di_utils, types
- **Top-level objects:**
  - `_SummaryDal` (class, line 14): No docstring; inferred from name/signature.
  - `_SummaryDal.__init__` (method, line 15): No docstring; inferred from name/signature.
  - `_SummaryDal.get_metrics_overview` (method, line 19): No docstring; inferred from name/signature.
  - `_SummaryDal.close` (method, line 28): No docstring; inferred from name/signature.
  - `_SummaryDal.get_historical_data` (method, line 31): No docstring; inferred from name/signature.
  - `_TrainerDal` (class, line 35): No docstring; inferred from name/signature.
  - `_TrainerDal.__init__` (method, line 36): No docstring; inferred from name/signature.
  - `_TrainerDal.get_historical_data` (method, line 41): No docstring; inferred from name/signature.
  - `_TrainerDal.get_plan_for_day` (method, line 49): No docstring; inferred from name/signature.
  - `_RunGuidanceDal` (class, line 55): No docstring; inferred from name/signature.
  - `_RunGuidanceDal.__init__` (method, line 56): No docstring; inferred from name/signature.
  - `_RunGuidanceDal.get_historical_data` (method, line 60): No docstring; inferred from name/signature.
  - `_RunGuidanceDal.get_recent_running_workouts` (method, line 82): No docstring; inferred from name/signature.
  - `_RunGuidanceDal.get_plan_for_day` (method, line 88): No docstring; inferred from name/signature.
  - `_NarrativeBuilder` (class, line 92): No docstring; inferred from name/signature.
  - `_NarrativeBuilder.__init__` (method, line 93): No docstring; inferred from name/signature.
  - `_NarrativeBuilder.build_daily_narrative` (method, line 96): No docstring; inferred from name/signature.
  - `_StubTelegram` (class, line 101): No docstring; inferred from name/signature.
  - `_StubTelegram.__init__` (method, line 102): No docstring; inferred from name/signature.
  - `_StubTelegram.send_message` (method, line 105): No docstring; inferred from name/signature.
  - `_orchestrator_for` (function, line 110): No docstring; inferred from name/signature.
  - `test_get_daily_summary_uses_builder` (function, line 129): No docstring; inferred from name/signature.
  - `test_get_daily_summary_appends_running_backoff_guidance` (function, line 149): No docstring; inferred from name/signature.
  - `test_build_trainer_message_includes_session` (function, line 171): No docstring; inferred from name/signature.
  - `test_send_telegram_message_uses_client` (function, line 184): No docstring; inferred from name/signature.

### `tests/application/test_progression_service.py`
- **Key imports:** __future__, dataclasses, pete_e.application.progression_service, pete_e.domain.progression, pytest, typing
- **Top-level objects:**
  - `StubDal` (class, line 13): No docstring; inferred from name/signature.
  - `StubDal.__post_init__` (method, line 19): No docstring; inferred from name/signature.
  - `StubDal.get_plan_week` (method, line 24): No docstring; inferred from name/signature.
  - `StubDal.load_lift_log` (method, line 27): No docstring; inferred from name/signature.
  - `StubDal.get_historical_metrics` (method, line 31): No docstring; inferred from name/signature.
  - `StubDal.update_workout_targets` (method, line 36): No docstring; inferred from name/signature.
  - `StubDal.refresh_plan_view` (method, line 39): No docstring; inferred from name/signature.
  - `_make_plan_rows` (function, line 43): No docstring; inferred from name/signature.
  - `test_calibrate_plan_week_fetches_and_persists` (function, line 59): No docstring; inferred from name/signature.
  - `test_calibrate_plan_week_can_skip_persistence` (function, line 112): No docstring; inferred from name/signature.

### `tests/application/test_validation_service.py`
- **Key imports:** __future__, datetime, pete_e.application.validation_service, pete_e.domain.validation, pytest, tests.config_stub, tests.mock_dal, typing
- **Top-level objects:**
  - `StubDal` (class, line 21): No docstring; inferred from name/signature.
  - `StubDal.__init__` (method, line 22): No docstring; inferred from name/signature.
  - `StubDal.get_historical_data` (method, line 37): No docstring; inferred from name/signature.
  - `StubDal.get_active_plan` (method, line 41): No docstring; inferred from name/signature.
  - `StubDal.find_plan_by_start_date` (method, line 44): No docstring; inferred from name/signature.
  - `StubDal.get_plan_muscle_volume` (method, line 47): No docstring; inferred from name/signature.
  - `StubDal.get_actual_muscle_volume` (method, line 50): No docstring; inferred from name/signature.
  - `StubDal.get_data_for_validation` (method, line 53): No docstring; inferred from name/signature.
  - `StubDal.apply_plan_backoff` (method, line 57): No docstring; inferred from name/signature.
  - `_make_decision` (function, line 67): No docstring; inferred from name/signature.
  - `test_validation_service_applies_adjustment` (function, line 95): No docstring; inferred from name/signature.
  - `test_validation_service_handles_no_application` (function, line 150): No docstring; inferred from name/signature.
  - `ComprehensiveDal` (class, line 167): No docstring; inferred from name/signature.
  - `ComprehensiveDal.__init__` (method, line 168): No docstring; inferred from name/signature.
  - `ComprehensiveDal.get_active_plan` (method, line 182): No docstring; inferred from name/signature.
  - `ComprehensiveDal.find_plan_by_start_date` (method, line 185): No docstring; inferred from name/signature.
  - `ComprehensiveDal.get_historical_data` (method, line 188): No docstring; inferred from name/signature.
  - `ComprehensiveDal.get_plan_muscle_volume` (method, line 192): No docstring; inferred from name/signature.
  - `ComprehensiveDal.get_actual_muscle_volume` (method, line 196): No docstring; inferred from name/signature.
  - `test_mock_dal_get_data_for_validation_compiles_expected_payload` (function, line 201): No docstring; inferred from name/signature.

### `tests/cli/test_generate_plan_cli.py`
- **Key imports:** datetime, importlib, pytest, unittest
- **Top-level objects:**
  - `generate_plan_module` (function, line 9): No docstring; inferred from name/signature.
  - `test_generate_plan_cli_invokes_service` (function, line 14): No docstring; inferred from name/signature.

### `tests/cli/test_sync_wger_catalog_cli.py`
- **Key imports:** importlib, pytest, unittest
- **Top-level objects:**
  - `sync_module` (function, line 8): No docstring; inferred from name/signature.
  - `test_catalog_sync_cli_invokes_service` (function, line 12): No docstring; inferred from name/signature.

### `tests/config/test_settings.py`
- **Key imports:** datetime, pete_e.config.config, psycopg.conninfo, pytest
- **Top-level objects:**
  - `base_settings_data` (function, line 9): No docstring; inferred from name/signature.
  - `test_database_url_uses_postgres_host` (function, line 34): No docstring; inferred from name/signature.
  - `test_database_url_uses_override` (function, line 49): No docstring; inferred from name/signature.
  - `test_log_path_fallback_notice_is_consumed_once` (function, line 66): No docstring; inferred from name/signature.

### `tests/config_stub.py`
- **Module purpose (docstring):** Provide a minimal pete_e.config stub for tests.
- **Key imports:** __future__, datetime, os, pathlib, sys, types, typing
- **Top-level objects:**
  - `Settings` (class, line 27): Light-weight stand in for the production Settings class used in tests.
  - `Settings.__init__` (method, line 30): No docstring; inferred from name/signature.
  - `Settings.build_database_url` (method, line 74): No docstring; inferred from name/signature.
  - `Settings.log_path` (method, line 90): No docstring; inferred from name/signature.
  - `Settings.consume_log_path_notice` (method, line 94): No docstring; inferred from name/signature.
  - `Settings._resolve_log_path` (method, line 103): No docstring; inferred from name/signature.
  - `Settings.phrases_path` (method, line 107): No docstring; inferred from name/signature.
  - `get_env` (function, line 111): No docstring; inferred from name/signature.

### `tests/conftest.py`
- **Key imports:** datetime, os, pathlib, sys, types
- **Top-level objects:**
  - `pytest_configure` (function, line 531): Ensure environment variables are populated for settings initialisation.

### `tests/di_utils.py`
- **Key imports:** __future__, pete_e.application.services, pete_e.domain.daily_sync, pete_e.infrastructure.di_container, pete_e.infrastructure.postgres_dal, pete_e.infrastructure.wger_client, typing
- **Top-level objects:**
  - `build_stub_container` (function, line 14): Construct a container seeded with stubbed dependencies for tests.
  - `_NoopDailySyncService` (class, line 42): No docstring; inferred from name/signature.
  - `_NoopDailySyncService.__init__` (method, line 43): No docstring; inferred from name/signature.
  - `_NoopDailySyncService.run_full` (method, line 47): No docstring; inferred from name/signature.
  - `_NoopDailySyncService.run_withings_only` (method, line 51): No docstring; inferred from name/signature.

### `tests/domain/test_cycle_service.py`
- **Key imports:** __future__, datetime, pete_e.application.orchestrator, pete_e.domain.cycle_service, tests.di_utils, unittest.mock
- **Top-level objects:**
  - `test_check_and_rollover_requires_four_weeks_and_sunday` (function, line 15): No docstring; inferred from name/signature.
  - `test_check_and_rollover_shorter_plans_roll_immediately` (function, line 29): No docstring; inferred from name/signature.
  - `test_orchestrator_delegates_rollover_decision` (function, line 40): No docstring; inferred from name/signature.

### `tests/domain/test_entities.py`
- **Key imports:** datetime, pete_e.config, pete_e.domain.entities
- **Top-level objects:**
  - `test_exercise_apply_progression_updates_weight` (function, line 13): No docstring; inferred from name/signature.
  - `test_exercise_apply_progression_handles_missing_history` (function, line 28): No docstring; inferred from name/signature.
  - `test_week_apply_progression_returns_notes` (function, line 37): No docstring; inferred from name/signature.
  - `test_plan_muscle_totals_accumulates_sets` (function, line 58): No docstring; inferred from name/signature.
  - `test_compute_recovery_flag_detects_poor_recovery` (function, line 77): No docstring; inferred from name/signature.

### `tests/domain/test_running_planner.py`
- **Key imports:** datetime, pete_e.domain, pete_e.domain.running_planner
- **Top-level objects:**
  - `_recent_beginner_runs` (function, line 11): No docstring; inferred from name/signature.
  - `test_running_planner_builds_foundation_block_from_low_run_base` (function, line 19): No docstring; inferred from name/signature.
  - `test_running_planner_builds_recovery_week_when_health_metrics_are_poor` (function, line 52): No docstring; inferred from name/signature.
  - `test_morning_run_adjustment_downgrades_planned_quality_when_recovery_dips` (function, line 88): No docstring; inferred from name/signature.

### `tests/domain/test_validation.py`
- **Key imports:** datetime, pathlib, pete_e.domain.validation, pytest, sys, types, typing
- **Top-level objects:**
  - `_make_rows` (function, line 50): Produce 'days' rows ending at base_date with constant hr_resting and sleep_total_minutes.
  - `patch_log_path` (function, line 66): No docstring; inferred from name/signature.
  - `test_baselines_use_recent_medians` (function, line 78): No docstring; inferred from name/signature.
  - `test_baselines_accept_prefetched_rows` (function, line 87): No docstring; inferred from name/signature.
  - `test_backoff_none_when_within_thresholds` (function, line 97): No docstring; inferred from name/signature.
  - `test_backoff_triggers_on_rhr_increase` (function, line 107): No docstring; inferred from name/signature.
  - `test_backoff_triggers_on_sleep_drop` (function, line 120): No docstring; inferred from name/signature.

### `tests/infrastructure/test_decorators.py`
- **Key imports:** __future__, pete_e.infrastructure.decorators, pete_e.infrastructure.wger_client, pytest, typing
- **Top-level objects:**
  - `DummyClient` (class, line 11): No docstring; inferred from name/signature.
  - `DummyClient.__init__` (method, line 12): No docstring; inferred from name/signature.
  - `DummyClient._should_retry` (method, line 17): No docstring; inferred from name/signature.
  - `DummyClient.run` (method, line 21): No docstring; inferred from name/signature.
  - `_FakeResponse` (class, line 28): No docstring; inferred from name/signature.
  - `_FakeResponse.__init__` (method, line 29): No docstring; inferred from name/signature.
  - `_response_with_status` (function, line 34): No docstring; inferred from name/signature.
  - `test_retry_on_network_error_retries_retryable_status` (function, line 38): No docstring; inferred from name/signature.
  - `test_retry_on_network_error_stops_on_non_retryable_status` (function, line 54): No docstring; inferred from name/signature.
  - `test_retry_on_network_error_handles_network_errors` (function, line 64): No docstring; inferred from name/signature.
  - `test_retry_on_network_error_raises_after_exhausting_retries` (function, line 79): No docstring; inferred from name/signature.

### `tests/infrastructure/test_mappers.py`
- **Module purpose (docstring):** Tests for infrastructure mappers bridging persistence, domain, and API payloads.
- **Key imports:** __future__, datetime, pete_e.infrastructure.mappers, pytest
- **Top-level objects:**
  - `sample_rows` (function, line 13): No docstring; inferred from name/signature.
  - `test_database_rows_to_payload_round_trip` (function, line 49): No docstring; inferred from name/signature.
  - `test_invalid_rows_raise_validation_error` (function, line 75): No docstring; inferred from name/signature.
  - `test_scheduled_time_wins_over_semantic_slot_for_persistence` (function, line 88): No docstring; inferred from name/signature.

### `tests/infrastructure/test_telegram_client.py`
- **Key imports:** __future__, pete_e.infrastructure.telegram_client, pytest, typing
- **Top-level objects:**
  - `_DummyResponse` (class, line 10): No docstring; inferred from name/signature.
  - `_DummyResponse.__init__` (method, line 11): No docstring; inferred from name/signature.
  - `_DummyResponse.raise_for_status` (method, line 14): No docstring; inferred from name/signature.
  - `_DummyResponse.json` (method, line 17): No docstring; inferred from name/signature.
  - `test_send_message_posts_expected_payload` (function, line 21): No docstring; inferred from name/signature.
  - `test_get_updates_calls_expected_url_and_params` (function, line 42): No docstring; inferred from name/signature.
  - `test_ping_calls_get_me_and_reports_configured_bot` (function, line 63): No docstring; inferred from name/signature.
  - `test_ping_requires_chat_id` (function, line 83): No docstring; inferred from name/signature.

### `tests/infrastructure/test_token_storage.py`
- **Key imports:** json, os, pete_e.infrastructure.token_storage, pytest
- **Top-level objects:**
  - `test_read_tokens_returns_none_when_missing` (function, line 9): No docstring; inferred from name/signature.
  - `test_save_and_read_tokens_round_trip` (function, line 15): No docstring; inferred from name/signature.
  - `test_save_tokens_sets_restrictive_permissions` (function, line 29): No docstring; inferred from name/signature.

### `tests/infrastructure/test_wger_client.py`
- **Key imports:** __future__, pete_e.infrastructure.wger_client, pytest, types
- **Top-level objects:**
  - `test_ping_checks_authenticated_endpoint_and_reports_host` (function, line 10): No docstring; inferred from name/signature.
  - `test_delete_all_days_ignores_stale_404` (function, line 40): No docstring; inferred from name/signature.
  - `test_ensure_custom_exercise_reuses_existing_translation` (function, line 81): No docstring; inferred from name/signature.
  - `test_ensure_custom_exercise_updates_existing_translation_when_description_changes` (function, line 128): No docstring; inferred from name/signature.
  - `test_ensure_custom_exercise_creates_exercise_and_translation` (function, line 192): No docstring; inferred from name/signature.

### `tests/mock_dal.py`
- **Module purpose (docstring):** Utilities for constructing DataAccessLayer test doubles.
- **Key imports:** __future__, datetime, pete_e.domain.data_access, pete_e.domain.validation, typing
- **Top-level objects:**
  - `MockableDal` (class, line 11): Concrete DataAccessLayer with inert implementations. Tests can subclass this base and override only the behaviours that are relevant for the scenario under test. All other methods …
  - `MockableDal.save_withings_daily` (method, line 23): No docstring; inferred from name/signature.
  - `MockableDal.save_withings_measure_groups` (method, line 43): No docstring; inferred from name/signature.
  - `MockableDal.save_wger_log` (method, line 51): No docstring; inferred from name/signature.
  - `MockableDal.load_lift_log` (method, line 62): No docstring; inferred from name/signature.
  - `MockableDal.get_daily_summary` (method, line 73): No docstring; inferred from name/signature.
  - `MockableDal.get_historical_metrics` (method, line 76): No docstring; inferred from name/signature.
  - `MockableDal.get_historical_data` (method, line 79): No docstring; inferred from name/signature.
  - `MockableDal.get_recent_running_workouts` (method, line 84): No docstring; inferred from name/signature.
  - `MockableDal.get_recent_strength_workouts` (method, line 92): No docstring; inferred from name/signature.
  - `MockableDal.get_metrics_overview` (method, line 100): No docstring; inferred from name/signature.
  - `MockableDal.get_data_for_validation` (method, line 103): No docstring; inferred from name/signature.
  - `MockableDal.refresh_daily_summary` (method, line 148): No docstring; inferred from name/signature.
  - `MockableDal.compute_body_age_for_date` (method, line 151): No docstring; inferred from name/signature.
  - `MockableDal.compute_body_age_for_range` (method, line 159): No docstring; inferred from name/signature.
  - `MockableDal.save_training_plan` (method, line 171): No docstring; inferred from name/signature.
  - `MockableDal.has_any_plan` (method, line 174): No docstring; inferred from name/signature.
  - `MockableDal.get_plan` (method, line 177): No docstring; inferred from name/signature.
  - `MockableDal.find_plan_by_start_date` (method, line 180): No docstring; inferred from name/signature.
  - `MockableDal.mark_plan_active` (method, line 185): No docstring; inferred from name/signature.
  - `MockableDal.deactivate_active_training_cycles` (method, line 188): No docstring; inferred from name/signature.
  - `MockableDal.create_training_cycle` (method, line 191): No docstring; inferred from name/signature.
  - `MockableDal.get_active_training_cycle` (method, line 205): No docstring; inferred from name/signature.
  - `MockableDal.update_training_cycle_state` (method, line 208): No docstring; inferred from name/signature.
  - `MockableDal.get_plan_muscle_volume` (method, line 220): No docstring; inferred from name/signature.
  - `MockableDal.get_actual_muscle_volume` (method, line 225): No docstring; inferred from name/signature.
  - `MockableDal.get_active_plan` (method, line 233): No docstring; inferred from name/signature.
  - `MockableDal.get_plan_week` (method, line 236): No docstring; inferred from name/signature.
  - `MockableDal.update_workout_targets` (method, line 239): No docstring; inferred from name/signature.
  - `MockableDal.refresh_plan_view` (method, line 242): No docstring; inferred from name/signature.
  - `MockableDal.refresh_actual_view` (method, line 245): No docstring; inferred from name/signature.
  - `MockableDal.apply_plan_backoff` (method, line 248): No docstring; inferred from name/signature.
  - `MockableDal.upsert_wger_categories` (method, line 260): No docstring; inferred from name/signature.
  - `MockableDal.upsert_wger_equipment` (method, line 263): No docstring; inferred from name/signature.
  - `MockableDal.upsert_wger_muscles` (method, line 266): No docstring; inferred from name/signature.
  - `MockableDal.upsert_wger_exercises` (method, line 269): No docstring; inferred from name/signature.
  - `MockableDal.save_validation_log` (method, line 275): No docstring; inferred from name/signature.
  - `MockableDal.was_week_exported` (method, line 278): No docstring; inferred from name/signature.
  - `MockableDal.record_wger_export` (method, line 281): No docstring; inferred from name/signature.

### `tests/rich_stub.py`
- **Module purpose (docstring):** Provide a light-weight stub for the rich library used in tests.
- **Key imports:** __future__, sys, types
- **Top-level objects:** none

### `tests/test_api_cli_commands.py`
- **Key imports:** pete_e, pete_e.application.exceptions, pete_e.application.sync, pete_e.cli, pete_e.cli.status, pytest, sys, typer.testing, types
- **Top-level objects:**
  - `request_stub` (function, line 68): No docstring; inferred from name/signature.
  - `enable_api_key` (function, line 73): No docstring; inferred from name/signature.
  - `test_status_endpoint_returns_checks` (function, line 77): No docstring; inferred from name/signature.
  - `test_status_endpoint_requires_valid_api_key` (function, line 100): No docstring; inferred from name/signature.
  - `test_sync_endpoint_returns_sync_result` (function, line 107): No docstring; inferred from name/signature.
  - `test_logs_endpoint_returns_tail` (function, line 139): No docstring; inferred from name/signature.
  - `test_sync_command_handles_data_access_error` (function, line 151): No docstring; inferred from name/signature.
  - `test_plan_command_handles_validation_error` (function, line 165): No docstring; inferred from name/signature.

### `tests/test_apple_dropbox_client.py`
- **Key imports:** __future__, datetime, dropbox.exceptions, dropbox.files, pete_e.infrastructure.apple_dropbox_client, types, typing
- **Top-level objects:**
  - `_make_file` (function, line 12): No docstring; inferred from name/signature.
  - `FakeDropbox` (class, line 17): No docstring; inferred from name/signature.
  - `FakeDropbox.__init__` (method, line 18): No docstring; inferred from name/signature.
  - `FakeDropbox.files_list_folder` (method, line 33): No docstring; inferred from name/signature.
  - `FakeDropbox.files_list_folder_continue` (method, line 45): No docstring; inferred from name/signature.
  - `_build_client` (function, line 68): No docstring; inferred from name/signature.
  - `test_find_new_export_files_uses_incremental_listing` (function, line 80): No docstring; inferred from name/signature.
  - `test_find_new_export_files_falls_back_on_cursor_error` (function, line 120): No docstring; inferred from name/signature.

### `tests/test_apple_dropbox_ingest.py`
- **Key imports:** datetime, io, json, pete_e.application, pete_e.domain.daily_sync, pete_e.infrastructure.apple_health_ingestor, pytest, types, typing, zipfile
- **Top-level objects:**
  - `_build_dummy_writer` (function, line 19): No docstring; inferred from name/signature.
  - `test_get_json_from_content_supports_zip_files` (function, line 36): No docstring; inferred from name/signature.
  - `test_ingestor_processes_new_files` (function, line 48): No docstring; inferred from name/signature.
  - `test_ingestor_skips_already_processed_files` (function, line 146): No docstring; inferred from name/signature.
  - `test_ingestor_raises_on_parser_failure` (function, line 213): No docstring; inferred from name/signature.
  - `test_application_wrapper_uses_injected_ingestor` (function, line 276): No docstring; inferred from name/signature.

### `tests/test_apple_hrv_vo2.py`
- **Key imports:** datetime, pete_e.cli, pete_e.domain, pete_e.infrastructure.apple_parser, pytest
- **Top-level objects:**
  - `_DeterministicRandom` (class, line 10): No docstring; inferred from name/signature.
  - `_DeterministicRandom.choice` (method, line 11): No docstring; inferred from name/signature.
  - `_DeterministicRandom.randint` (method, line 16): No docstring; inferred from name/signature.
  - `_DeterministicRandom.random` (method, line 19): No docstring; inferred from name/signature.
  - `fixed_random` (function, line 24): No docstring; inferred from name/signature.
  - `stub_phrase_picker` (function, line 33): No docstring; inferred from name/signature.
  - `test_apple_parser_maps_hrv_and_vo2_metrics` (function, line 37): No docstring; inferred from name/signature.
  - `test_daily_summary_appends_hrv_trend_line` (function, line 69): No docstring; inferred from name/signature.
  - `test_body_age_uses_direct_vo2_max` (function, line 105): No docstring; inferred from name/signature.
  - `test_body_age_uses_enriched_withings_body_comp_after_first_full_window` (function, line 118): No docstring; inferred from name/signature.
  - `test_body_age_falls_back_before_enriched_withings_window_is_complete` (function, line 140): No docstring; inferred from name/signature.

### `tests/test_body_age_summary.py`
- **Key imports:** datetime, pete_e.cli, pete_e.domain, pytest
- **Top-level objects:**
  - `StubDal` (class, line 9): No docstring; inferred from name/signature.
  - `StubDal.__init__` (method, line 10): No docstring; inferred from name/signature.
  - `StubDal.get_historical_data` (method, line 13): No docstring; inferred from name/signature.
  - `make_row` (function, line 21): No docstring; inferred from name/signature.
  - `StubOrchestrator` (class, line 25): No docstring; inferred from name/signature.
  - `StubOrchestrator.__init__` (method, line 26): No docstring; inferred from name/signature.
  - `StubOrchestrator.get_daily_summary` (method, line 31): No docstring; inferred from name/signature.
  - `test_get_body_age_trend_computes_delta` (function, line 36): No docstring; inferred from name/signature.
  - `test_get_body_age_trend_handles_missing_history` (function, line 53): No docstring; inferred from name/signature.
  - `test_build_daily_summary_appends_body_age_line` (function, line 63): No docstring; inferred from name/signature.
  - `test_build_daily_summary_shows_na_when_missing` (function, line 80): No docstring; inferred from name/signature.
  - `test_weekly_narrative_includes_body_age_trend` (function, line 90): No docstring; inferred from name/signature.

### `tests/test_check_auth.py`
- **Key imports:** __future__, datetime, json, os, scripts.check_auth
- **Top-level objects:**
  - `test_withings_status_ok_when_token_file_present` (function, line 15): No docstring; inferred from name/signature.
  - `test_withings_status_warns_when_only_env_refresh_token` (function, line 29): No docstring; inferred from name/signature.
  - `test_withings_status_requires_setup_when_app_config_present` (function, line 38): No docstring; inferred from name/signature.
  - `test_withings_status_flags_missing_app_settings` (function, line 53): No docstring; inferred from name/signature.
  - `test_dropbox_status_ok_when_all_present` (function, line 65): No docstring; inferred from name/signature.
  - `test_dropbox_status_prompts_for_refresh_token_only` (function, line 78): No docstring; inferred from name/signature.
  - `test_dropbox_status_prompts_for_multiple_missing` (function, line 87): No docstring; inferred from name/signature.
  - `test_env_loader_handles_export_and_quotes` (function, line 97): No docstring; inferred from name/signature.

### `tests/test_cron_schedule.py`
- **Key imports:** __future__, csv, pathlib, pete_e.infrastructure.cron_manager, re
- **Top-level objects:**
  - `_load_rows` (function, line 14): No docstring; inferred from name/signature.
  - `test_core_automation_jobs_are_present_and_enabled` (function, line 19): No docstring; inferred from name/signature.
  - `test_core_automation_jobs_point_to_live_entry_points` (function, line 33): No docstring; inferred from name/signature.
  - `test_enabled_python_module_jobs_point_to_existing_scripts` (function, line 42): No docstring; inferred from name/signature.
  - `test_rendered_crontab_includes_core_jobs_and_omits_disabled_entries` (function, line 54): No docstring; inferred from name/signature.

### `tests/test_cycle_initiation.py`
- **Key imports:** __future__, datetime, pete_e.cli, pytest, typer.testing
- **Top-level objects:**
  - `cli_runner` (function, line 12): No docstring; inferred from name/signature.
  - `test_lets_begin_seeds_strength_test_week_when_macrocycle_missing` (function, line 16): No docstring; inferred from name/signature.
  - `test_lets_begin_defaults_to_next_monday` (function, line 61): No docstring; inferred from name/signature.

### `tests/test_cycle_rollover.py`
- **Key imports:** __future__, datetime, pete_e.application.exceptions, pete_e.application.orchestrator, pytest, tests.config_stub, tests.di_utils, types
- **Top-level objects:**
  - `StubPlanService` (class, line 15): No docstring; inferred from name/signature.
  - `StubPlanService.__init__` (method, line 16): No docstring; inferred from name/signature.
  - `StubPlanService.create_next_plan_for_cycle` (method, line 20): No docstring; inferred from name/signature.
  - `StubExportService` (class, line 25): No docstring; inferred from name/signature.
  - `StubExportService.__init__` (method, line 26): No docstring; inferred from name/signature.
  - `StubExportService.export_plan_week` (method, line 29): No docstring; inferred from name/signature.
  - `StubDal` (class, line 42): No docstring; inferred from name/signature.
  - `StubDal.__init__` (method, line 43): No docstring; inferred from name/signature.
  - `StubDal.get_active_plan` (method, line 46): No docstring; inferred from name/signature.
  - `StubDal.close` (method, line 49): No docstring; inferred from name/signature.
  - `make_orchestrator` (function, line 53): No docstring; inferred from name/signature.
  - `test_run_cycle_rollover_creates_plan_and_exports` (function, line 64): No docstring; inferred from name/signature.
  - `test_run_cycle_rollover_raises_when_plan_creation_errors` (function, line 78): No docstring; inferred from name/signature.
  - `test_run_end_to_end_week_triggers_rollover_when_due` (function, line 91): No docstring; inferred from name/signature.
  - `test_run_end_to_end_week_exports_next_week_when_rollover_not_due` (function, line 113): No docstring; inferred from name/signature.
  - `test_run_end_to_end_week_aligns_to_previous_sunday` (function, line 132): When the review runs late (e.g., Monday AM), cadence checks should still fire.

### `tests/test_day_in_life.py`
- **Key imports:** __future__, datetime, pete_e.application.services, pytest, types, typing
- **Top-level objects:**
  - `StubValidationService` (class, line 12): No docstring; inferred from name/signature.
  - `StubValidationService.__init__` (method, line 13): No docstring; inferred from name/signature.
  - `StubValidationService.validate_and_adjust_plan` (method, line 16): No docstring; inferred from name/signature.
  - `StubValidationService.get_adherence_snapshot` (method, line 20): No docstring; inferred from name/signature.
  - `StubDal` (class, line 24): No docstring; inferred from name/signature.
  - `StubDal.__init__` (method, line 25): No docstring; inferred from name/signature.
  - `StubDal.was_week_exported` (method, line 33): No docstring; inferred from name/signature.
  - `StubDal.get_plan_week_rows` (method, line 37): No docstring; inferred from name/signature.
  - `StubDal.record_wger_export` (method, line 40): No docstring; inferred from name/signature.
  - `StubWgerClient` (class, line 46): No docstring; inferred from name/signature.
  - `StubWgerClient.__init__` (method, line 47): No docstring; inferred from name/signature.
  - `StubWgerClient.find_or_create_routine` (method, line 50): No docstring; inferred from name/signature.
  - `StubWgerClient.delete_all_days_in_routine` (method, line 54): No docstring; inferred from name/signature.
  - `test_export_service_builds_payload_and_records` (function, line 58): No docstring; inferred from name/signature.
  - `test_export_service_respects_existing_export` (function, line 72): No docstring; inferred from name/signature.

### `tests/test_dropbox.py`
- **Key imports:** dropbox, os, sys
- **Top-level objects:**
  - `main` (function, line 11): No docstring; inferred from name/signature.

### `tests/test_environmental_commentary.py`
- **Key imports:** datetime, pete_e.domain, pete_e.domain.narrative_builder, pytest
- **Top-level objects:**
  - `_DeterministicRandom` (class, line 9): No docstring; inferred from name/signature.
  - `_DeterministicRandom.choice` (method, line 10): No docstring; inferred from name/signature.
  - `_DeterministicRandom.randint` (method, line 15): No docstring; inferred from name/signature.
  - `_DeterministicRandom.random` (method, line 18): No docstring; inferred from name/signature.
  - `fixed_random` (function, line 23): No docstring; inferred from name/signature.
  - `stub_phrase_picker` (function, line 32): No docstring; inferred from name/signature.
  - `_base_summary` (function, line 36): No docstring; inferred from name/signature.
  - `test_daily_summary_includes_environment_colour` (function, line 52): No docstring; inferred from name/signature.
  - `test_daily_summary_skips_environment_when_absent` (function, line 65): No docstring; inferred from name/signature.

### `tests/test_failure_modes.py`
- **Module purpose (docstring):** Regression tests for tricky network behaviours.
- **Key imports:** __future__, datetime, mocks.requests_mock, pete_e.domain.token_storage, pete_e.infrastructure, pete_e.infrastructure.withings_client, typing, unittest.mock
- **Top-level objects:**
  - `DummyResponse` (class, line 16): No docstring; inferred from name/signature.
  - `DummyResponse.__init__` (method, line 17): No docstring; inferred from name/signature.
  - `DummyResponse.raise_for_status` (method, line 22): No docstring; inferred from name/signature.
  - `DummyResponse.json` (method, line 26): No docstring; inferred from name/signature.
  - `test_withings_client_retries_rate_limits` (function, line 30): No docstring; inferred from name/signature.
  - `test_withings_client_reloads_tokens_when_storage_changes` (function, line 102): No docstring; inferred from name/signature.
  - `test_withings_summary_collects_all_measure_groups_and_derives_water_percent` (function, line 127): No docstring; inferred from name/signature.

### `tests/test_french_trainer_message.py`
- **Module purpose (docstring):** Tests for the deterministic construction of French trainer messages.
- **Key imports:** __future__, pete_e.domain, pete_e.domain.french_trainer, pytest, tests
- **Top-level objects:**
  - `deterministic_phrase` (function, line 12): No docstring; inferred from name/signature.
  - `test_compose_daily_message_includes_highlights_and_context` (function, line 20): No docstring; inferred from name/signature.
  - `test_compose_daily_message_handles_missing_metrics` (function, line 44): No docstring; inferred from name/signature.

### `tests/test_full_cycle.py`
- **Key imports:** __future__, datetime, pete_e.domain.cycle_service
- **Top-level objects:**
  - `test_cycle_service_detects_four_week_rollover` (function, line 8): No docstring; inferred from name/signature.
  - `test_cycle_service_requires_active_plan` (function, line 16): No docstring; inferred from name/signature.
  - `test_cycle_service_waits_until_end_of_block` (function, line 22): No docstring; inferred from name/signature.

### `tests/test_hrv_vo2_tuning.py`
- **Key imports:** datetime, pete_e.config, pete_e.domain.plan_factory, pete_e.domain.repositories, pete_e.domain.validation, pytest, tests.config_stub, typing
- **Top-level objects:**
  - `PlanBuilderStubRepo` (class, line 15): Stub that implements the PlanRepository interface for plan builder tests. This replaces the old PlanBuilderStubDal.
  - `PlanBuilderStubRepo.__init__` (method, line 21): No docstring; inferred from name/signature.
  - `PlanBuilderStubRepo.get_latest_training_maxes` (method, line 26): No docstring; inferred from name/signature.
  - `PlanBuilderStubRepo.save_full_plan` (method, line 30): No docstring; inferred from name/signature.
  - `PlanBuilderStubRepo.get_assistance_pool_for` (method, line 35): No docstring; inferred from name/signature.
  - `PlanBuilderStubRepo.get_core_pool_ids` (method, line 38): No docstring; inferred from name/signature.
  - `_hrv_row` (function, line 42): No docstring; inferred from name/signature.
  - `test_downward_hrv_trend_triggers_backoff` (function, line 52): No docstring; inferred from name/signature.
  - `test_high_vo2_increases_conditioning_volume` (function, line 74): This test is rewritten to use the PlanFactory and a PlanRepository stub. It no longer calls the non-existent 'build_block'.

### `tests/test_ingestion_resilience.py`
- **Key imports:** __future__, pete_e.application.sync, pete_e.infrastructure, pete_e.infrastructure.apple_parser, pytest, typing
- **Top-level objects:**
  - `capture_logs` (function, line 13): No docstring; inferred from name/signature.
  - `test_apple_parser_handles_partial_rows_without_crashing` (function, line 23): No docstring; inferred from name/signature.
  - `test_sync_result_summary_includes_withings_note` (function, line 189): No docstring; inferred from name/signature.
  - `test_sync_result_summary_handles_multi_day_window` (function, line 206): No docstring; inferred from name/signature.

### `tests/test_logging_rotation.py`
- **Key imports:** logging, logging.handlers, pete_e, pytest
- **Top-level objects:**
  - `temp_logger` (function, line 12): No docstring; inferred from name/signature.
  - `test_rotating_handler_defaults` (function, line 26): No docstring; inferred from name/signature.
  - `test_rotating_handler_rollover` (function, line 36): No docstring; inferred from name/signature.

### `tests/test_message_formatting.py`
- Parse error: invalid non-printable character U+FEFF (<unknown>, line 1)

### `tests/test_message_snapshots.py`
- **Key imports:** datetime, pete_e.domain, pete_e.domain.narrative_builder, pytest
- **Top-level objects:**
  - `_DeterministicRandom` (class, line 9): Deterministic random stub so snapshot output stays stable.
  - `_DeterministicRandom.choice` (method, line 12): No docstring; inferred from name/signature.
  - `_DeterministicRandom.randint` (method, line 17): No docstring; inferred from name/signature.
  - `_DeterministicRandom.random` (method, line 20): No docstring; inferred from name/signature.
  - `snapshot_context` (function, line 25): No docstring; inferred from name/signature.
  - `test_daily_message_snapshot` (function, line 41): No docstring; inferred from name/signature.
  - `test_weekly_message_snapshot` (function, line 76): No docstring; inferred from name/signature.

### `tests/test_metrics_service_stats.py`
- **Module purpose (docstring):** Focused tests for statistics helpers in :mod:`pete_e.domain.metrics_service`.
- **Key imports:** __future__, datetime, pete_e.domain, pytest, tests
- **Top-level objects:**
  - `sample_series` (function, line 13): No docstring; inferred from name/signature.
  - `test_calculate_moving_averages` (function, line 19): No docstring; inferred from name/signature.
  - `test_find_historical_extremes` (function, line 31): No docstring; inferred from name/signature.
  - `test_build_metric_stats_coerces_to_floats` (function, line 43): No docstring; inferred from name/signature.
  - `test_get_metrics_overview_integration` (function, line 53): No docstring; inferred from name/signature.

### `tests/test_nudges.py`
- **Key imports:** __future__, datetime, pete_e.domain.plan_factory, pete_e.domain.repositories
- **Top-level objects:**
  - `StubRepository` (class, line 9): No docstring; inferred from name/signature.
  - `StubRepository.get_assistance_pool_for` (method, line 10): No docstring; inferred from name/signature.
  - `StubRepository.get_core_pool_ids` (method, line 13): No docstring; inferred from name/signature.
  - `StubRepository.get_latest_training_maxes` (method, line 16): No docstring; inferred from name/signature.
  - `StubRepository.save_full_plan` (method, line 19): No docstring; inferred from name/signature.
  - `test_strength_test_plan_contains_all_main_lifts` (function, line 23): No docstring; inferred from name/signature.

### `tests/test_orchestrator.py`
- **Key imports:** __future__, contextlib, datetime, pete_e.application.orchestrator, pete_e.domain.daily_sync, pytest, tests.config_stub, tests.di_utils, types
- **Top-level objects:**
  - `StubDal` (class, line 16): No docstring; inferred from name/signature.
  - `StubDal.__init__` (method, line 17): No docstring; inferred from name/signature.
  - `StubDal.get_active_plan` (method, line 20): No docstring; inferred from name/signature.
  - `StubDal.close` (method, line 23): No docstring; inferred from name/signature.
  - `StubValidationService` (class, line 27): No docstring; inferred from name/signature.
  - `StubValidationService.__init__` (method, line 28): No docstring; inferred from name/signature.
  - `StubValidationService.validate_and_adjust_plan` (method, line 32): No docstring; inferred from name/signature.
  - `_make_orchestrator` (function, line 37): No docstring; inferred from name/signature.
  - `test_run_weekly_calibration_reports_message` (function, line 53): No docstring; inferred from name/signature.
  - `test_run_end_to_end_week_triggers_rollover` (function, line 65): No docstring; inferred from name/signature.
  - `test_run_end_to_end_week_exports_when_rollover_skipped` (function, line 100): No docstring; inferred from name/signature.
  - `test_run_end_to_end_week_repeats_prior_week_when_adherence_is_low` (function, line 129): No docstring; inferred from name/signature.
  - `test_run_end_to_end_day_sends_summary` (function, line 168): No docstring; inferred from name/signature.
  - `test_generate_strength_test_week_creates_and_exports` (function, line 211): No docstring; inferred from name/signature.
  - `test_generate_and_deploy_next_plan_uses_cycle_creation` (function, line 239): No docstring; inferred from name/signature.
  - `test_generate_strength_test_week_serializes_plan_generation` (function, line 268): No docstring; inferred from name/signature.

### `tests/test_orchestrator_e2e.py`
- **Key imports:** __future__, datetime, pete_e.application.orchestrator, tests.di_utils, types
- **Top-level objects:**
  - `test_dataclasses_capture_expected_fields` (function, line 10): No docstring; inferred from name/signature.
  - `test_close_invokes_dal_close` (function, line 20): No docstring; inferred from name/signature.

### `tests/test_plan_builder.py`
- **Key imports:** datetime, pathlib, pete_e.domain, pete_e.domain.plan_factory, pete_e.domain.repositories, pytest, sys, types
- **Top-level objects:**
  - `_StubSettings` (class, line 10): No docstring; inferred from name/signature.
  - `_StubSettings.__init__` (method, line 11): No docstring; inferred from name/signature.
  - `DummyRepo` (class, line 25): Fake PlanRepository to simulate database lookups and record calls. This replaces the old DummyDAL that was mocking plan_rw.
  - `DummyRepo.__init__` (method, line 30): No docstring; inferred from name/signature.
  - `DummyRepo.get_latest_training_maxes` (method, line 35): No docstring; inferred from name/signature.
  - `DummyRepo.save_full_plan` (method, line 44): No docstring; inferred from name/signature.
  - `DummyRepo.get_assistance_pool_for` (method, line 49): No docstring; inferred from name/signature.
  - `DummyRepo.get_core_pool_ids` (method, line 54): No docstring; inferred from name/signature.
  - `repo` (function, line 60): Fixture to provide an instance of our fake repository.
  - `test_plan_factory_builds_correct_block_structure` (function, line 65): This test replaces the old test_block_structure. It now tests the PlanFactory directly, which is responsible for the business logic of creating the plan structure.

### `tests/test_plan_generation.py`
- **Key imports:** __future__, contextlib, datetime, pete_e.application.plan_generation, tests.config_stub
- **Top-level objects:**
  - `test_plan_generation_service_holds_lock` (function, line 11): No docstring; inferred from name/signature.

### `tests/test_plan_service.py`
- **Key imports:** __future__, datetime, pete_e.application.services, pete_e.domain, pete_e.domain.plan_factory, pete_e.domain.repositories, pytest, tests.config_stub, typing
- **Top-level objects:**
  - `StubPlanRepository` (class, line 16): No docstring; inferred from name/signature.
  - `StubPlanRepository.__init__` (method, line 17): No docstring; inferred from name/signature.
  - `StubPlanRepository.get_assistance_pool_for` (method, line 27): No docstring; inferred from name/signature.
  - `StubPlanRepository.get_core_pool_ids` (method, line 30): No docstring; inferred from name/signature.
  - `StubPlanRepository.get_latest_training_maxes` (method, line 33): No docstring; inferred from name/signature.
  - `StubPlanRepository.save_full_plan` (method, line 36): No docstring; inferred from name/signature.
  - `_training_maxes` (function, line 41): No docstring; inferred from name/signature.
  - `test_plan_factory_computes_expected_targets` (function, line 50): No docstring; inferred from name/signature.
  - `test_plan_service_persists_full_plan` (function, line 80): No docstring; inferred from name/signature.

### `tests/test_plan_validation_structure.py`
- **Key imports:** datetime, pete_e.domain, pete_e.domain.entities, pete_e.domain.validation, pytest, typing
- **Top-level objects:**
  - `_make_day` (function, line 53): No docstring; inferred from name/signature.
  - `make_valid_plan` (function, line 88): No docstring; inferred from name/signature.
  - `test_validate_plan_structure_accepts_valid_plan` (function, line 117): No docstring; inferred from name/signature.
  - `test_validate_plan_structure_rejects_incorrect_week_count` (function, line 123): No docstring; inferred from name/signature.
  - `test_validate_plan_structure_rejects_week_number_mismatch` (function, line 132): No docstring; inferred from name/signature.
  - `test_validate_plan_structure_requires_seven_day_spacing` (function, line 141): No docstring; inferred from name/signature.
  - `test_validate_plan_structure_requires_training_day_pattern` (function, line 150): No docstring; inferred from name/signature.
  - `test_validate_plan_structure_flags_muscle_imbalance` (function, line 161): No docstring; inferred from name/signature.
  - `test_validate_plan_structure_flags_missing_weights` (function, line 175): No docstring; inferred from name/signature.

### `tests/test_pool_shutdown.py`
- **Key imports:** pete_e.application, pete_e.application.orchestrator, pete_e.application.sync, pytest, tests.di_utils, unittest.mock
- **Top-level objects:**
  - `test_orchestrator_close_method_closes_dal` (function, line 11): Tests that the Orchestrator's close method correctly calls the close method on its DAL. This replaces the old decorator test.
  - `test_run_sync_with_retries_closes_orchestrator_and_pool` (function, line 41): Tests that the main sync function properly closes the orchestrator's resources (and thus the connection pool) after execution, both on success and failure.

### `tests/test_postgres_dal.py`
- **Key imports:** datetime, pete_e.infrastructure.postgres_dal, unittest, unittest.mock
- **Top-level objects:**
  - `TestPostgresDal` (class, line 8): No docstring; inferred from name/signature.
  - `TestPostgresDal.test_save_withings_daily` (method, line 11): Test that save_withings_daily executes the correct SQL.
  - `TestPostgresDal.test_save_withings_measure_groups` (method, line 42): No docstring; inferred from name/signature.
  - `TestPostgresDal.test_get_historical_data` (method, line 82): Test that get_historical_data queries the daily_summary table.
  - `TestPostgresDal.test_refresh_daily_summary_refreshes_inputs_before_body_age` (method, line 113): No docstring; inferred from name/signature.
  - `TestPostgresDal.test_get_core_pool_ids_reads_core_pool_table_when_present` (method, line 136): No docstring; inferred from name/signature.
  - `TestPostgresDal.test_get_core_pool_ids_falls_back_to_categories_without_core_pool` (method, line 156): No docstring; inferred from name/signature.

### `tests/test_progression.py`
- **Key imports:** __future__, pete_e.config, pete_e.domain.entities, pete_e.domain.progression, tests, typing
- **Top-level objects:**
  - `make_metrics` (function, line 12): No docstring; inferred from name/signature.
  - `make_week` (function, line 19): No docstring; inferred from name/signature.
  - `_run_progression` (function, line 25): No docstring; inferred from name/signature.
  - `test_low_rir_good_recovery` (function, line 41): No docstring; inferred from name/signature.
  - `test_high_rir_good_recovery` (function, line 65): No docstring; inferred from name/signature.
  - `test_poor_recovery_halves_increment` (function, line 88): No docstring; inferred from name/signature.
  - `test_missing_history_keeps_target` (function, line 111): No docstring; inferred from name/signature.
  - `test_no_rir_uses_weight_and_recovery` (function, line 137): No docstring; inferred from name/signature.

### `tests/test_progression_helpers.py`
- **Module purpose (docstring):** Additional unit coverage for progression helper functions.
- **Key imports:** __future__, pete_e.config, pete_e.domain.progression, pytest, tests
- **Top-level objects:**
  - `_make_metrics` (function, line 11): No docstring; inferred from name/signature.
  - `test_compute_recovery_flag_defaults_to_true_with_missing_data` (function, line 18): No docstring; inferred from name/signature.
  - `test_compute_recovery_flag_detects_poor_recovery` (function, line 25): No docstring; inferred from name/signature.
  - `test_adjust_exercise_with_no_history_returns_message` (function, line 31): No docstring; inferred from name/signature.
  - `test_adjust_exercise_increases_weight_when_rir_low` (function, line 38): No docstring; inferred from name/signature.
  - `test_adjust_exercise_decreases_weight_for_high_rir` (function, line 51): No docstring; inferred from name/signature.
  - `test_adjust_exercise_handles_missing_weight_entries` (function, line 65): No docstring; inferred from name/signature.

### `tests/test_readiness_alerts.py`
- **Key imports:** __future__, datetime, pete_e.application.services, typing
- **Top-level objects:**
  - `StrengthDalStub` (class, line 9): No docstring; inferred from name/signature.
  - `StrengthDalStub.__init__` (method, line 10): No docstring; inferred from name/signature.
  - `StrengthDalStub.get_latest_training_maxes` (method, line 14): No docstring; inferred from name/signature.
  - `StrengthDalStub.save_full_plan` (method, line 17): No docstring; inferred from name/signature.
  - `test_create_strength_test_week_persists_plan` (function, line 23): No docstring; inferred from name/signature.

### `tests/test_sanity_checks.py`
- **Key imports:** __future__, datetime, pete_e.application.services, pytest, types, typing
- **Top-level objects:**
  - `StubValidationService` (class, line 12): No docstring; inferred from name/signature.
  - `StubValidationService.validate_and_adjust_plan` (method, line 13): No docstring; inferred from name/signature.
  - `StubValidationService.get_adherence_snapshot` (method, line 24): No docstring; inferred from name/signature.
  - `DryRunDal` (class, line 28): No docstring; inferred from name/signature.
  - `DryRunDal.__init__` (method, line 29): No docstring; inferred from name/signature.
  - `DryRunDal.was_week_exported` (method, line 34): No docstring; inferred from name/signature.
  - `DryRunDal.get_plan_week_rows` (method, line 37): No docstring; inferred from name/signature.
  - `DryRunDal.record_wger_export` (method, line 40): No docstring; inferred from name/signature.
  - `test_export_service_dry_run_returns_payload` (function, line 44): No docstring; inferred from name/signature.

### `tests/test_schema_integrations.py`
- **Key imports:** __future__, datetime, pathlib, pete_e.cli, pete_e.domain, pete_e.domain.narrative_builder, pytest, re, typing
- **Top-level objects:**
  - `_DeterministicRandom` (class, line 15): No docstring; inferred from name/signature.
  - `_DeterministicRandom.choice` (method, line 16): No docstring; inferred from name/signature.
  - `_DeterministicRandom.randint` (method, line 21): No docstring; inferred from name/signature.
  - `_DeterministicRandom.random` (method, line 24): No docstring; inferred from name/signature.
  - `fixed_random` (function, line 29): No docstring; inferred from name/signature.
  - `stub_phrase_picker` (function, line 38): No docstring; inferred from name/signature.
  - `_extract_table_columns` (function, line 42): No docstring; inferred from name/signature.
  - `test_withings_daily_table_includes_body_composition_columns` (function, line 59): No docstring; inferred from name/signature.
  - `test_withings_raw_measure_group_table_is_present` (function, line 76): No docstring; inferred from name/signature.
  - `test_body_age_table_tracks_enriched_body_comp_usage` (function, line 84): No docstring; inferred from name/signature.
  - `test_training_plan_schema_includes_single_active_index_and_core_pool` (function, line 94): No docstring; inferred from name/signature.
  - `test_schema_permissions_block_only_grants_to_pete_user_when_role_exists` (function, line 102): No docstring; inferred from name/signature.
  - `test_daily_summary_view_select_includes_expected_columns` (function, line 149): No docstring; inferred from name/signature.
  - `test_daily_summary_pipeline_surfaces_new_schema_fields` (function, line 163): No docstring; inferred from name/signature.

### `tests/test_status_cli.py`
- Parse error: invalid non-printable character U+FEFF (<unknown>, line 1)

### `tests/test_strength_test.py`
- **Key imports:** __future__, datetime, pete_e.domain.plan_factory, pete_e.domain.repositories
- **Top-level objects:**
  - `MinimalRepository` (class, line 9): No docstring; inferred from name/signature.
  - `MinimalRepository.get_assistance_pool_for` (method, line 10): No docstring; inferred from name/signature.
  - `MinimalRepository.get_core_pool_ids` (method, line 13): No docstring; inferred from name/signature.
  - `MinimalRepository.get_latest_training_maxes` (method, line 16): No docstring; inferred from name/signature.
  - `MinimalRepository.save_full_plan` (method, line 19): No docstring; inferred from name/signature.
  - `test_strength_test_plan_marks_amrap_comment` (function, line 23): No docstring; inferred from name/signature.

### `tests/test_strength_test_service.py`
- **Key imports:** __future__, datetime, pete_e.application.services, pete_e.application.strength_test, pete_e.domain, pytest, tests.config_stub, typing
- **Top-level objects:**
  - `_expected_tm` (function, line 15): No docstring; inferred from name/signature.
  - `StrengthTestDal` (class, line 20): No docstring; inferred from name/signature.
  - `StrengthTestDal.__init__` (method, line 21): No docstring; inferred from name/signature.
  - `StrengthTestDal.get_latest_test_week` (method, line 32): No docstring; inferred from name/signature.
  - `StrengthTestDal.get_plan_week_rows` (method, line 39): No docstring; inferred from name/signature.
  - `StrengthTestDal.load_lift_log` (method, line 49): No docstring; inferred from name/signature.
  - `StrengthTestDal.insert_strength_test_result` (method, line 74): No docstring; inferred from name/signature.
  - `StrengthTestDal.upsert_training_max` (method, line 77): No docstring; inferred from name/signature.
  - `StrengthTestDal.get_latest_training_maxes` (method, line 81): No docstring; inferred from name/signature.
  - `StrengthTestDal.get_assistance_pool_for` (method, line 84): No docstring; inferred from name/signature.
  - `StrengthTestDal.get_core_pool_ids` (method, line 87): No docstring; inferred from name/signature.
  - `StrengthTestDal.save_full_plan` (method, line 90): No docstring; inferred from name/signature.
  - `test_strength_test_service_updates_training_maxes_from_logged_amraps` (function, line 95): No docstring; inferred from name/signature.
  - `test_create_next_plan_for_cycle_uses_refreshed_training_maxes` (function, line 112): No docstring; inferred from name/signature.

### `tests/test_strength_week_integration.py`
- **Key imports:** __future__, datetime, pete_e.domain, pete_e.domain.plan_factory, pete_e.domain.repositories
- **Top-level objects:**
  - `StaticRepository` (class, line 10): No docstring; inferred from name/signature.
  - `StaticRepository.get_assistance_pool_for` (method, line 11): No docstring; inferred from name/signature.
  - `StaticRepository.get_core_pool_ids` (method, line 14): No docstring; inferred from name/signature.
  - `StaticRepository.get_latest_training_maxes` (method, line 17): No docstring; inferred from name/signature.
  - `StaticRepository.save_full_plan` (method, line 20): No docstring; inferred from name/signature.
  - `test_531_block_plan_includes_blaze_sessions` (function, line 24): No docstring; inferred from name/signature.
  - `test_531_block_plan_includes_core_work` (function, line 42): No docstring; inferred from name/signature.

### `tests/test_sunday_review.py`
- **Key imports:** __future__, datetime, pete_e.application.orchestrator, tests.di_utils, types
- **Top-level objects:**
  - `PassiveDal` (class, line 10): No docstring; inferred from name/signature.
  - `PassiveDal.__init__` (method, line 11): No docstring; inferred from name/signature.
  - `PassiveDal.get_active_plan` (method, line 14): No docstring; inferred from name/signature.
  - `PassiveDal.close` (method, line 17): No docstring; inferred from name/signature.
  - `build_orchestrator` (function, line 21): No docstring; inferred from name/signature.
  - `test_run_end_to_end_week_skips_rollover_when_not_due` (function, line 33): No docstring; inferred from name/signature.

### `tests/test_sync_summary_log.py`
- **Key imports:** __future__, pete_e, pete_e.application, typing
- **Top-level objects:**
  - `_StubOrchestrator` (class, line 9): No docstring; inferred from name/signature.
  - `_StubOrchestrator.__init__` (method, line 10): No docstring; inferred from name/signature.
  - `_StubOrchestrator.run_daily_sync` (method, line 13): No docstring; inferred from name/signature.
  - `_final_summary_bundle` (function, line 17): No docstring; inferred from name/signature.
  - `test_run_sync_logs_single_summary_line_success` (function, line 34): No docstring; inferred from name/signature.
  - `test_run_sync_logs_failure_summary_once` (function, line 80): No docstring; inferred from name/signature.

### `tests/test_telegram_alerts.py`
- **Key imports:** __future__, json, pete_e.infrastructure, pete_e.infrastructure.wger_client, pytest, requests, types
- **Top-level objects:**
  - `_FakeResponse` (class, line 13): No docstring; inferred from name/signature.
  - `_FakeResponse.__init__` (method, line 14): No docstring; inferred from name/signature.
  - `_FakeResponse.json` (method, line 19): No docstring; inferred from name/signature.
  - `_response` (function, line 23): No docstring; inferred from name/signature.
  - `_configured_client` (function, line 27): No docstring; inferred from name/signature.
  - `test_wger_client_retry_logic` (function, line 37): No docstring; inferred from name/signature.
  - `test_wger_client_request_retries_and_succeeds` (function, line 44): No docstring; inferred from name/signature.
  - `test_wger_client_request_raises_after_non_retryable` (function, line 84): No docstring; inferred from name/signature.

### `tests/test_telegram_listener.py`
- **Key imports:** __future__, datetime, json, os, pathlib, pete_e.application, pete_e.application.telegram_listener, pete_e.config, pytest, types
- **Top-level objects:**
  - `_make_update` (function, line 18): No docstring; inferred from name/signature.
  - `StubTelegramClient` (class, line 30): No docstring; inferred from name/signature.
  - `StubTelegramClient.__init__` (method, line 31): No docstring; inferred from name/signature.
  - `StubTelegramClient.get_updates` (method, line 39): No docstring; inferred from name/signature.
  - `StubTelegramClient.send_message` (method, line 47): No docstring; inferred from name/signature.
  - `StubTelegramClient.send_alert` (method, line 51): No docstring; inferred from name/signature.
  - `test_listen_once_handles_summary_command` (function, line 56): No docstring; inferred from name/signature.
  - `test_listen_once_runs_sync_and_reports_status` (function, line 87): No docstring; inferred from name/signature.
  - `test_listen_once_triggers_strength_test_week` (function, line 124): No docstring; inferred from name/signature.
  - `test_listen_once_uses_stored_offset` (function, line 157): No docstring; inferred from name/signature.

### `tests/test_trend_commentary.py`
- Parse error: invalid non-printable character U+FEFF (<unknown>, line 1)

### `tests/test_utils_converters.py`
- **Module purpose (docstring):** Unit tests for small utility helpers in :mod:`pete_e.utils`.
- **Key imports:** __future__, datetime, decimal, pete_e.utils, pytest, random, typing
- **Top-level objects:**
  - `test_to_float_handles_various_inputs` (function, line 14): No docstring; inferred from name/signature.
  - `test_to_date_accepts_common_representations` (function, line 29): No docstring; inferred from name/signature.
  - `test_minutes_to_hours_normalises_to_float` (function, line 42): No docstring; inferred from name/signature.
  - `test_ensure_sentence_appends_punctuation` (function, line 49): No docstring; inferred from name/signature.
  - `test_choose_from_respects_defaults` (function, line 55): No docstring; inferred from name/signature.
  - `test_average_skips_none` (function, line 71): No docstring; inferred from name/signature.
  - `test_mean_or_none_and_near_helpers` (function, line 79): No docstring; inferred from name/signature.

### `tests/test_validation_adherence.py`
- **Key imports:** __future__, datetime, pete_e.domain.validation, pytest, tests.config_stub, typing
- **Top-level objects:**
  - `_make_history` (function, line 17): No docstring; inferred from name/signature.
  - `_build_snapshot` (function, line 47): No docstring; inferred from name/signature.
  - `plan_start` (function, line 77): No docstring; inferred from name/signature.
  - `test_low_adherence_reduces_volume` (function, line 81): No docstring; inferred from name/signature.
  - `test_high_adherence_increases_volume_when_recovery_good` (function, line 118): No docstring; inferred from name/signature.
  - `test_high_adherence_blocked_when_recovery_flagged` (function, line 155): No docstring; inferred from name/signature.

### `tests/test_weekly_calibration.py`
- **Key imports:** __future__, datetime, pete_e.application.orchestrator, tests.di_utils, types
- **Top-level objects:**
  - `DummyDal` (class, line 10): No docstring; inferred from name/signature.
  - `DummyDal.get_active_plan` (method, line 11): No docstring; inferred from name/signature.
  - `DummyDal.close` (method, line 14): No docstring; inferred from name/signature.
  - `StubValidationService` (class, line 18): No docstring; inferred from name/signature.
  - `StubValidationService.__init__` (method, line 19): No docstring; inferred from name/signature.
  - `StubValidationService.validate_and_adjust_plan` (method, line 22): No docstring; inferred from name/signature.
  - `build_orchestrator` (function, line 27): No docstring; inferred from name/signature.
  - `test_run_weekly_calibration_uses_next_monday` (function, line 40): No docstring; inferred from name/signature.

### `tests/test_weekly_plan_message.py`
- Parse error: invalid non-printable character U+FEFF (<unknown>, line 1)

### `tests/test_wger_exporter.py`
- **Key imports:** __future__, pete_e.infrastructure.wger_client
- **Top-level objects:**
  - `test_set_config_posts_payload` (function, line 6): No docstring; inferred from name/signature.
  - `test_set_config_posts_weight_payload` (function, line 29): No docstring; inferred from name/signature.
  - `test_set_config_posts_rest_payload` (function, line 52): No docstring; inferred from name/signature.

### `tests/test_wger_sender.py`
- **Key imports:** __future__, datetime, pete_e.application, pytest, types
- **Top-level objects:**
  - `stub_validation` (function, line 12): No docstring; inferred from name/signature.
  - `RecordingDal` (class, line 34): No docstring; inferred from name/signature.
  - `RecordingDal.__init__` (method, line 35): No docstring; inferred from name/signature.
  - `RecordingDal.was_week_exported` (method, line 38): No docstring; inferred from name/signature.
  - `RecordingDal.get_plan_week_rows` (method, line 41): No docstring; inferred from name/signature.
  - `RecordingDal.record_wger_export` (method, line 44): No docstring; inferred from name/signature.
  - `test_push_week_forwards_to_export_service` (function, line 48): No docstring; inferred from name/signature.
  - `test_push_week_logs_skip_when_exported` (function, line 86): No docstring; inferred from name/signature.

### `tests/test_withings_muscle_water.py`
- Parse error: invalid non-printable character U+FEFF (<unknown>, line 1)

### `tests/test_withings_token_permissions.py`
- **Key imports:** os, pete_e.domain.token_storage, pete_e.infrastructure, pete_e.infrastructure.withings_client, pytest, unittest.mock
- **Top-level objects:**
  - `test_save_tokens_sets_owner_only_permissions` (function, line 12): No docstring; inferred from name/signature.
  - `test_oauth_helper_sets_owner_only_permissions` (function, line 27): No docstring; inferred from name/signature.

## Pass 2: How modules work together

- **Entry points:** `pete_e/api.py`, scripts under `scripts/`, and CLI modules under `pete_e/cli/` initiate workflows.
- **Application layer (`pete_e/application`)** orchestrates use-cases: plan generation, sync jobs, telegram interactions, validation, and progression services.
- **Domain layer (`pete_e/domain`)** contains core business logic and entities: planning rules, cycles, metrics, body age, narratives, schedule rules, and data contracts.
- **Infrastructure layer (`pete_e/infrastructure`)** adapts external systems: Postgres DAL, Withings/WGER/Telegram/Dropbox clients, parsing, token storage, and DI wiring.
- **Utilities/config/logging** provide cross-cutting concerns used by all layers.
- **Migrations + schema** define data persistence contracts consumed by infrastructure/data-access code.
- **Tests** map closely to layers and end-to-end behavior, providing regression coverage for orchestration and integrations.

## Pass 3: Potential issues from rapid/vibe-coded evolution

- `pete_e/api.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/application/catalog_sync.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/application/orchestrator.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/application/progression_service.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/application/services.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/application/sync.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/application/telegram_listener.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/application/validation_service.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/application/wger_sender.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/cli/messenger.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/cli/messenger.py` uses `print(...)`; consider structured logging consistency.
- `pete_e/cli/status.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/domain/body_age.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/domain/daily_sync.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/domain/french_trainer.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/domain/metrics_service.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/domain/narrative_builder.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/domain/running_planner.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/domain/validation.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/infrastructure/apple_health_ingestor.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/infrastructure/cron_manager.py` uses `print(...)`; consider structured logging consistency.
- `pete_e/infrastructure/git_utils.py` uses `print(...)`; consider structured logging consistency.
- `pete_e/infrastructure/postgres_dal.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/infrastructure/telegram_client.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/infrastructure/token_storage.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/infrastructure/withings_client.py` catches broad `Exception`; error handling may hide root causes.
- `pete_e/infrastructure/withings_oauth_helper.py` uses `print(...)`; consider structured logging consistency.
- `pete_e/logging_setup.py` uses `print(...)`; consider structured logging consistency.
- `scripts/check_auth.py` uses `print(...)`; consider structured logging consistency.
- `scripts/heartbeat_check.py` catches broad `Exception`; error handling may hide root causes.
- `scripts/inspect_withings_response.py` uses `print(...)`; consider structured logging consistency.
- `scripts/run_sunday_review.py` catches broad `Exception`; error handling may hide root causes.
- `scripts/send_telegram_message.py` catches broad `Exception`; error handling may hide root causes.
- `scripts/send_telegram_message.py` uses `print(...)`; consider structured logging consistency.
- `tests/conftest.py` catches broad `Exception`; error handling may hide root causes.
- `tests/test_dropbox.py` catches broad `Exception`; error handling may hide root causes.