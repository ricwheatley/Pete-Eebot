# Migration Note — Prompt 12 Release Readiness

Date: 2026-05-07

## Scope
This note summarizes the module moves completed through the refactor plan, compatibility guarantees for public API contracts, and the recommended rollback strategy.

## Module moves summary

### API surface decomposition
- Route handlers are grouped under `pete_e/api_routes/`:
  - `metrics.py`
  - `plan.py`
  - `status_sync.py`
  - `logs_webhooks.py`
  - shared auth/dependency wiring in `dependencies.py`
- `pete_e/api.py` now acts as composition/bootstrap that mounts those route modules.

### Orchestration split
- `pete_e/application/orchestrator.py` remains the main facade.
- Workflow logic has been moved into focused modules under `pete_e/application/workflows/`:
  - `daily_sync.py`
  - `weekly_calibration.py`
  - `cycle_rollover.py`
  - `trainer_message.py`

### Read-model and application services
- Plan read concerns are centralized in `pete_e/application/plan_read_model.py`.
- API-facing use cases continue to flow through `pete_e/application/api_services.py`.

### Contracts and composition
- Collaborator contracts/protocols are defined in `pete_e/application/collaborator_contracts.py`.
- Dependency composition remains centralized in `pete_e/infrastructure/di_container.py` and route dependency helpers.

## Compatibility guarantees

### Public API routes
- Route grouping was an internal reorganization; endpoint intent remains the same:
  - Metrics endpoints remain served from the metrics route module.
  - Plan endpoints remain served from the plan route module.
  - Status/sync and logs/webhooks remain under their dedicated route modules.

### Contract shape guarantees
- API contract tests validate stable response shape for key endpoints:
  - `metrics_overview` returns `{"columns", "rows"}`.
  - `plan_for_day` returns `{"columns", "rows"}` and preserves API-key auth behavior.
- These checks are covered in `tests/integration/test_api_contracts.py`.

### Backward-compatibility expectations
- Existing callers that depend on documented response keys (`columns`, `rows`) for key read endpoints should not require payload parser changes.
- Orchestrator public facade methods remain the integration point for CLI/automation entrypoints.

## Rollback strategy

### Trigger criteria
Rollback is recommended if any of the following occur in production:
- Endpoint payload shape drift for key consumers.
- Daily/weekly automation regressions (sync, calibration, rollover paths).
- Elevated error rates in orchestrator workflows after deploy.

### Rollback steps
1. Revert to the last known-good commit/tag before this refactor release.
2. Re-run smoke checks:
   - API contract checks (`tests/integration/test_api_contracts.py`).
   - Core orchestration tests (`tests/test_orchestrator.py`, workflow-specific suites).
3. Re-deploy the previous artifact with unchanged environment configuration.
4. Verify telemetry/log health for sync, plan, and webhook paths before resuming scheduled automations.

### Data and schema considerations
- No schema migration is coupled to this migration note itself.
- If rollback crosses DB migration boundaries, apply standard migration rollback/runbook before restoring application traffic.

## Verification run snapshot (2026-05-07)
- `pytest` currently fails during collection because a FastAPI test double used in one suite does not accept constructor kwargs.
- `ruff check .` currently reports unresolved lint debt in multiple files.
- `mypy pete_e tests` currently fails with duplicate module path discovery for `pete_e/api_routes/logs_webhooks.py`.
- `pytest tests/integration/test_api_contracts.py -q` passes and validates key endpoint response-shape compatibility.
