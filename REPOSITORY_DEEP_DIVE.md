# Pete-Eebot Repository Deep Dive (Post-Refactor)

_Last updated: May 8, 2026_

This document replaces the previous object-by-object inventory and reflects the **current architecture after the refactor program**. It focuses on module boundaries, runtime flows, test posture, and an honest assessment of product competitiveness.

---

## 1) Executive Snapshot

Pete-Eebot is now structured as a layered Python system:

- **API/routes layer** (`pete_e/api_routes/`): thin HTTP endpoints grouped by concern.
- **Application layer** (`pete_e/application/`): workflow orchestration, use-case services, contracts/composition.
- **Domain layer** (`pete_e/domain/`): core training/readiness/narrative rules.
- **Infrastructure layer** (`pete_e/infrastructure/`): Postgres DAL, external API/Dropbox/Telegram clients, mappers.
- **Entry points**: CLI commands in `pete_e/cli/`, FastAPI app bootstrap in `pete_e/api.py`, automation scripts in `scripts/`.

Compared to the stale pre-refactor state, orchestration concerns are now split into dedicated workflow modules, API routes are decomposed by resource, and test suites are explicitly layered (unit/service/integration).

---

## 2) Architecture Map (Current)

## 2.1 API / Transport Layer

### `pete_e/api.py`
- Primary FastAPI assembly/bootstrap.
- Wires route modules and dependency providers.
- Keeps runtime startup concerns in one place.

### `pete_e/api_routes/`
- `metrics.py`: read-only metrics/context endpoints.
- `plan.py`: plan-by-day/week retrieval endpoints.
- `status_sync.py`: operational health and sync triggers.
- `logs_webhooks.py`: log retrieval + GitHub webhook/deploy hooks.
- `root.py`: root/status convenience routes.
- `dependencies.py`: shared DI helpers for route modules.

**Why this matters:** endpoint logic is now grouped by capability and no longer concentrated in a single monolith file.

## 2.2 Application Layer

### Core orchestration
- `orchestrator.py`: thin façade coordinating high-level workflows and messaging.
- `workflows/daily_sync.py`: daily sync lifecycle.
- `workflows/weekly_calibration.py`: weekly validation/progression pass.
- `workflows/cycle_rollover.py`: cycle transition and export bootstrap.
- `workflows/trainer_message.py`: trainer-style message composition pipeline.

### Use-case services
- `services.py`: plan creation + export orchestration services.
- `plan_generation.py`: block generation workflow.
- `progression_service.py`: progression calibration adapter around domain logic.
- `validation_service.py`: adherence/validation orchestration.
- `plan_read_model.py`: centralized read-model normalization for plan snapshots.
- `plan_context_service.py`: plan context acquisition and fallback handling.
- `sync.py`, `wger_sync.py`, `wger_sender.py`, `catalog_sync.py`: integration-oriented use cases.
- `composition.py` + `collaborator_contracts.py`: dependency composition and contract boundaries.

**Why this matters:** orchestration complexity has been decomposed into explicit workflows with smaller testable surfaces.

## 2.3 Domain Layer

Key domain modules now host policy and rules instead of transport concerns:

- `progression.py`, `cycle_service.py`, `validation.py`: training lifecycle logic.
- `running_planner.py`, `schedule_rules.py`, `plan_factory.py`, `plan_mapper.py`: plan generation and schedule semantics.
- `metrics_service.py`, `body_age.py`: readiness/body-composition interpretation.
- `narrative_builder.py`, `narrative_utils.py`, `phrase_picker.py`, `french_trainer.py`: natural-language coaching output.
- `entities.py`, `repositories.py`, `data_access.py`: domain contracts/structures.

## 2.4 Infrastructure Layer

- `postgres_dal.py`, `db_conn.py`: persistence and connection management.
- `withings_client.py`, `wger_client.py`, `telegram_client.py`, `apple_dropbox_client.py`: external connectors.
- `apple_health_ingestor.py`, `apple_parser.py`, `apple_writer.py`: Apple Health ingest pipeline.
- `token_storage.py`, `withings_oauth_helper.py`: credential/token lifecycle.
- `cron_manager.py`, `log_utils.py`, `git_utils.py`: runtime operational utilities.
- `mappers/`: integration-specific mapping helpers (e.g., wger payload mapping).

---

## 3) Runtime Flows

## 3.1 Daily Automation

Typical path:
1. CLI/API trigger enters application orchestrator.
2. Daily sync workflow pulls data (Dropbox/Apple, Withings, wger as configured).
3. Persistence + derived metrics refresh.
4. Optional summary/trainer message generation.
5. Optional Telegram dispatch and logging checkpoints.

Primary modules: `application/orchestrator.py`, `application/workflows/daily_sync.py`, `application/sync.py`, `infrastructure/*clients.py`.

## 3.2 Weekly Automation

Typical path:
1. Weekly calibration workflow validates prior week and progression signals.
2. Cycle rollover workflow decides whether to continue, deload, or move to next block.
3. Export service pushes active week to wger with annotations/backoff logic.

Primary modules: `application/workflows/weekly_calibration.py`, `application/workflows/cycle_rollover.py`, `application/services.py`.

## 3.3 Read APIs

Metrics/plan endpoints are read-focused and rely on dedicated application services/read models rather than embedding SQL/shape logic directly in route handlers.

Primary modules: `api_routes/metrics.py`, `api_routes/plan.py`, `application/api_services.py`, `application/plan_read_model.py`.

---

## 4) Testing & Quality Posture

The repository now shows clear evidence of layered coverage:

- **Domain unit tests** under `tests/domain/`.
- **Application/service tests** under `tests/application/` and `tests/service/`.
- **API contract tests** under `tests/integration/`.
- Broad workflow/regression tests remain at repository root test namespace for end-to-end behaviors.

This test shape is consistent with the refactor goals: smaller seams, contract-oriented tests, and preserved integration confidence.

---

## 5) Operational Posture

Operational readiness has improved through:

- Cron-friendly command surfaces (`scripts/`, CLI commands).
- Health/status checks (`pete_e/cli/status.py`, route support in `status_sync.py`).
- Backup and review helpers (`scripts/backup_db.sh`, `scripts/run_sunday_review.py`).
- Structured logging support (`pete_e/logging_setup.py`, domain/infrastructure logging helpers).

The app remains optimized for lightweight self-hosted operation (e.g., Raspberry Pi class environments), which is a strong differentiator for private personal analytics workflows.

---

## 6) Competitive Assessment — “How competition-worthy is it now?”

## Overall score: **7.8 / 10 (strong niche contender)**

## Strengths
- **Architecture maturity:** clear layering and decomposed workflows.
- **Automation breadth:** daily + weekly loops with practical operational tooling.
- **Data fusion:** combines readiness, composition, and training planning in one stack.
- **Self-hosted pragmatism:** low-ops deployment model for a privacy-sensitive user.
- **Test depth:** broad, multi-layered test suite.

## Gaps vs top-tier commercial coach platforms
- **Multi-user capability:** appears single-athlete oriented (not yet coach/team SaaS ready).
- **UI productization:** power is mostly CLI/API driven, with limited dedicated UX surfaces.
- **Observability/analytics product layer:** strong logs, but limited product dashboards and experiment loops.
- **Distribution moat:** lacks obvious ecosystem hooks (mobile app, marketplace, third-party plug-in economy).

## What would move it to 9/10
1. Add a simple authenticated web/mobile operator UI for plan review, overrides, and trend inspection.
2. Formalize model/data contracts and versioned API guarantees for external consumers.
3. Introduce user/tenant abstraction to support multiple athletes safely.
4. Expand benchmark metrics (adherence lift, injury-risk proxy, progression quality) as explicit KPIs.

---

## 7) Suggested Next Deep-Dive Maintenance Policy

To prevent staleness recurring:

- Update this document whenever any of these change: module boundaries, workflow ownership, route layout, or test layering.
- Keep this at architecture-level detail (not per-function catalog dumps).
- Add a short “refactor delta” section in future PRs that modify orchestration composition.

