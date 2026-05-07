# Pete-Eebot Refactor Execution Plan (Prompt-by-Prompt)

This plan translates the architecture inventory in `REPOSITORY_DEEP_DIVE.md` into an executable sequence of prompts you can run one at a time in an AI coding workflow.

## How to use this plan
- Run **one prompt at a time**.
- Require each prompt to finish with: code changes, tests, and a concise diff summary.
- Do not start the next prompt until the current prompt is green.

---

## Prompt 0 — Baseline and safety rails
**Goal:** Establish a known-good baseline before refactoring.

**Prompt to run:**
> Read `REPOSITORY_DEEP_DIVE.md` and map current module boundaries. Then run the project test suite and any lint/type checks currently configured. Produce a baseline report that includes:
> 1) passing/failing checks,
> 2) high-risk modules by coupling/size,
> 3) a proposed incremental migration order.
> Do not refactor yet.

**Expected output:** Baseline report + zero functional changes.

---

## Prompt 1 — Introduce explicit ports/contracts for orchestration dependencies
**Goal:** Decouple `Orchestrator` from concrete infrastructure/services.

**Prompt to run:**
> Add interface-style protocols/ABCs for the collaborators used by `pete_e/application/orchestrator.py` (data access, plan generation, export, sync, messaging). Wire existing concrete implementations to satisfy these contracts without changing behavior. Keep constructor injection backward compatible.

**Definition of done:**
- `Orchestrator` depends on contracts, not concrete classes.
- No behavior change.
- Tests pass.

---

## Prompt 2 — Split `orchestrator.py` into focused workflow modules
**Goal:** Break up the large orchestration class by use-case.

**Prompt to run:**
> Extract workflow logic from `pete_e/application/orchestrator.py` into focused modules:
> - weekly_calibration workflow,
> - cycle_rollover workflow,
> - daily_sync workflow,
> - trainer_message workflow,
> while preserving the public `Orchestrator` API. `Orchestrator` should become a thin façade.

**Definition of done:**
- New workflow modules created.
- `Orchestrator` retains existing method signatures.
- Existing tests updated and passing.

---

## Prompt 3 — Normalize API service response shaping
**Goal:** Reduce transformation duplication in `api_services.py`.

**Prompt to run:**
> Refactor `pete_e/application/api_services.py` by extracting shared response-shaping utilities for numeric coercion, JSON safety, windowing, and metric source metadata. Replace duplicated inline shaping logic in `MetricsService` methods with reusable helpers. Preserve endpoint payload compatibility.

**Definition of done:**
- Shared helper layer exists and is used.
- Output schemas unchanged.
- Regression tests for representative endpoints pass.

---

## Prompt 4 — Create a dedicated plan read-model layer
**Goal:** Separate read concerns from orchestration/application services.

**Prompt to run:**
> Introduce a plan read-model module that owns query/result normalization for daily/weekly plan snapshots and context retrieval (`plan_for_day`, `plan_for_week`, and related context loading). Update `PlanService`/API service usage to depend on the read-model.

**Definition of done:**
- Read queries centralized.
- Calling services simplified.
- Contract tests for day/week plans pass.

---

## Prompt 5 — Isolate wger export payload construction pipeline
**Goal:** Decompose `WgerExportService` complexity.

**Prompt to run:**
> Refactor `WgerExportService` internals into a staged pipeline:
> 1) row normalization,
> 2) payload assembly,
> 3) annotation/enrichment,
> 4) export ID resolution,
> 5) API submission.
> Keep `export_plan_week` signature and behavior stable.

**Definition of done:**
- Pipeline modules/functions are independently testable.
- Existing behavior preserved.
- Export-related tests pass.

---

## Prompt 6 — Consolidate date/time parsing and coercion utilities
**Goal:** Remove repeated coercion logic across application modules.

**Prompt to run:**
> Extract shared date/time and numeric coercion helpers currently duplicated across `api_services.py`, `orchestrator.py`, and `strength_test.py` into a common utility module. Replace local implementations and keep edge-case handling identical.

**Definition of done:**
- Single shared coercion utility.
- Removed duplication.
- Unit tests added for boundary parsing cases.

---

## Prompt 7 — Standardize error taxonomy and error mapping
**Goal:** Improve consistency in failure handling.

**Prompt to run:**
> Expand and apply `pete_e/application/exceptions.py` as the canonical application error taxonomy. Ensure workflows/services raise typed `ApplicationError` subclasses, and API layer maps them to stable HTTP responses/messages.

**Definition of done:**
- Consistent typed exceptions across app layer.
- Centralized API error mapping.
- Tests cover representative error paths.

---

## Prompt 8 — Dependency injection container alignment
**Goal:** Make composition explicit and test-friendly.

**Prompt to run:**
> Audit and refactor dependency composition points (including existing DI container usage) so application services and workflows are wired in one place with clear provider functions/factories. Add test fixtures that swap contract implementations for fast unit tests.

**Definition of done:**
- Clear composition root(s).
- Easier collaborator swapping in tests.
- No runtime behavior change.

---

## Prompt 9 — API layer simplification and endpoint grouping
**Goal:** Slim down `pete_e/api.py` into route modules.

**Prompt to run:**
> Split `pete_e/api.py` into route-group modules (metrics, plan, status/sync, logs/webhooks/auth helpers). Keep the same external routes and authentication semantics. Ensure app startup imports still work identically.

**Definition of done:**
- Route modules introduced.
- `api.py` becomes assembly/bootstrap.
- Endpoint compatibility tests pass.

---

## Prompt 10 — Test architecture refresh
**Goal:** Match tests to refactored architecture.

**Prompt to run:**
> Reorganize tests into layers:
> - pure unit tests for domain/application helpers,
> - service-level tests with mocked ports,
> - lightweight integration tests for API contracts.
> Remove brittle tests coupled to old internal structure while preserving coverage of behavior.

**Definition of done:**
- Clear test layering.
- Stable, fast default test run.
- Coverage on critical workflows maintained or improved.

---

## Prompt 11 — Observability and operational hardening pass
**Goal:** Ensure refactor remains operable in production.

**Prompt to run:**
> Add/standardize structured logs and key workflow checkpoints (daily sync, weekly calibration, rollover, export). Ensure logs include correlation context and outcome summaries without leaking secrets.

**Definition of done:**
- Consistent log fields and checkpoint coverage.
- Sensitive values redacted.
- Smoke tests pass.

---

## Prompt 12 — Final compatibility and release prep
**Goal:** Ship safely.

**Prompt to run:**
> Run full test/lint/type suite, verify API contract compatibility for key endpoints, and produce a migration note summarizing module moves, compatibility guarantees, and rollback strategy.

**Definition of done:**
- Full CI-equivalent checks green.
- Release notes/migration notes prepared.
- Refactor declared complete.

---

## Suggested execution order rationale
1. **Stabilize boundaries first** (contracts, split orchestrator).
2. **Refactor heavy complexity centers** (`api_services`, `WgerExportService`).
3. **Consolidate cross-cutting concerns** (coercion, errors, DI).
4. **Recompose interface layer** (`api.py` route grouping).
5. **Finish with test/observability/release hardening**.

## Acceptance criteria for the full refactor
- Public API routes and payloads remain backward compatible unless explicitly versioned.
- Daily/weekly automation behavior matches pre-refactor outcomes.
- Export workflows remain deterministic and auditable.
- Tests are faster, clearer, and less coupled to internals.
