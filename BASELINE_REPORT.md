# Baseline Engineering Report (2026-05-07)

## 1) Current module boundaries

Source: `REPOSITORY_DEEP_DIVE.md` inventory plus repository structure.

- **Interface / entrypoint layer**
  - `pete_e/api.py`: FastAPI endpoints, auth checks, endpoint wiring, webhook trigger.
  - `pete_e/cli/*`: Typer CLI commands, operator workflows, status/sync commands.
- **Application layer** (`pete_e/application/*`)
  - Orchestration and use-case services (`orchestrator.py`, `services.py`, `plan_generation.py`, `catalog_sync.py`, `sync.py`, etc.).
  - Converts interface intent (API/CLI) into domain operations and infrastructure calls.
- **Domain layer** (`pete_e/domain/*`)
  - Planning, progression, validation, narrative, and fitness logic (`validation.py`, `schedule_rules.py`, `running_planner.py`, etc.).
  - Business rules and transformations with minimal framework coupling.
- **Infrastructure layer** (`pete_e/infrastructure/*`)
  - External adapters: Postgres DAL, Wger integration, Apple/Withings ingestion, Telegram, DI container.
  - Persistence/network/IO concerns.
- **Config + utilities**
  - `pete_e/config/*`: settings and runtime configuration.
  - `pete_e/utils/*`: shared helper functionality.
- **Test and dependency fallback shims**
  - `tests/*`: full test suite.
  - `mocks/*`: local API-compatible shims for optional dependencies in constrained test envs.

### Boundary quality snapshot

- Architecture follows a **mostly-clean layering** (interface -> application -> domain + infrastructure).
- Largest cross-layer concentration is in `application.orchestrator` and `cli.messenger`, both coordinating many modules.

## 2) Checks run and outcomes

### Executed checks

1. `pytest`
   - **Result:** PASS
   - **Details:** `247 passed, 1 skipped`.

2. `ruff check .`
   - **Result:** FAIL
   - **Details:** `47` findings total (`F401/F841/E402/E731/F811/F821` mix).
   - Primary issue clusters:
     - Unused imports / variables across app, domain, infrastructure, and tests.
     - Import-order violations (`E402`) in `tests/test_plan_builder.py`.
     - One undefined name (`F821`) in `tests/test_apple_dropbox_client.py`.

## 3) High-risk modules by coupling and size

Heuristic used: line count + count of unique internal `pete_e.*` imports.

### Highest-size modules (top 10)

1. `pete_e/cli/messenger.py` — 1244 LOC, 15 internal deps
2. `pete_e/infrastructure/postgres_dal.py` — 1127 LOC, 6 internal deps
3. `pete_e/domain/validation.py` — 1003 LOC, 4 internal deps
4. `pete_e/application/orchestrator.py` — 830 LOC, 16 internal deps
5. `pete_e/domain/schedule_rules.py` — 825 LOC, 0 internal deps
6. `pete_e/application/services.py` — 673 LOC, 12 internal deps
7. `pete_e/infrastructure/apple_parser.py` — 654 LOC, 1 internal deps
8. `pete_e/application/api_services.py` — 523 LOC, 4 internal deps
9. `pete_e/domain/running_planner.py` — 516 LOC, 2 internal deps
10. `pete_e/domain/body_age.py` — 454 LOC, 1 internal deps

### Highest-coupling modules (top 10)

1. `pete_e/application/orchestrator.py` — 16 internal deps
2. `pete_e/cli/messenger.py` — 15 internal deps
3. `pete_e/application/services.py` — 12 internal deps
4. `pete_e/infrastructure/di_container.py` — 11 internal deps
5. `pete_e/infrastructure/postgres_dal.py` — 6 internal deps
6. `pete_e/infrastructure/apple_health_ingestor.py` — 6 internal deps
7. `pete_e/application/wger_sender.py` — 6 internal deps
8. `pete_e/api.py` — 5 internal deps
9. `pete_e/application/telegram_listener.py` — 5 internal deps
10. `pete_e/cli/status.py` — 5 internal deps

### Risk interpretation

- **Highest-risk now:**
  - `cli/messenger.py` (very large, broad dependencies, integration-heavy).
  - `application/orchestrator.py` (core coordinator; broad fan-in/fan-out).
  - `application/services.py` (high orchestration + export complexity).
  - `infrastructure/postgres_dal.py` (large IO-heavy adapter, high blast radius).
- **Domain complexity risks:**
  - `domain/validation.py` and `domain/schedule_rules.py` are large logic surfaces, even with lower coupling.

## 4) Proposed incremental migration order (no refactor yet)

Goal: reduce risk with smallest safe slices first, preserving behavior.

1. **Stabilize quality gate (lint debt first)**
   - Fix deterministic lint errors in tests and low-risk modules.
   - Enforce clean `ruff check` as merge gate before structural moves.

2. **Extract CLI command handlers from `cli/messenger.py`**
   - Split by command domain (sync, planning, status, messaging) into submodules.
   - Keep Typer wiring thin; move logic behind application services.

3. **Decompose `application/orchestrator.py` into workflow components**
   - Introduce dedicated workflow units: daily sync, weekly calibration, rollover/export.
   - Keep orchestrator as composition root/facade.

4. **Decompose `application/services.py` export pipeline**
   - Isolate payload shaping, annotation, and exporter side effects.
   - Add stable interface boundaries for easier mocking.

5. **Split `infrastructure/postgres_dal.py` by bounded concern**
   - Separate read models, write models, ingestion writes, and plan operations.
   - Keep one DAL facade initially to avoid broad caller churn.

6. **Modularize large domain files (`validation.py`, `schedule_rules.py`)**
   - Extract pure rule families into smaller modules with explicit contracts.
   - Backfill with focused tests before moving any logic.

7. **Finalize with dependency-direction hardening**
   - Add architecture tests/lint rules preventing interface/infrastructure leakage into domain.
   - Document allowed imports per layer.

## 5) Immediate baseline conclusions

- Functional regression risk is currently low from a test perspective (suite is green).
- Structural and maintainability risk is elevated due to concentrated large/coupled modules.
- Best near-term move is **lint cleanup + boundary extraction around CLI/orchestrator**, then DAL/domain decomposition.

