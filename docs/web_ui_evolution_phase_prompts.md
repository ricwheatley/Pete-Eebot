# Web UI Evolution — Ready-to-Run Prompt Series

Use these prompts **in order**. Each prompt is designed for one implementation pass and asks for concrete code changes, tests, and docs updates.

> Tip: Paste one prompt at a time into a fresh chat for best results.

## Phase 0 — Stabilize baseline (1–2 weeks)

### Prompt 0.1 — Baseline runbook + topology
```text
I’m implementing Phase 0 of docs/web_ui_evolution_plan.md.

Task:
1) Audit the current runtime/deploy topology (CLI entry points, cron/systemd hooks, API service startup path, DB migration path).
2) Create/update a source-of-truth runbook in docs/ that includes:
   - local dev run steps
   - production service run steps
   - deploy flow summary
   - backup/restore quick commands
   - smoke-check commands after deploy
3) Keep it aligned to what actually exists in this repo right now (no aspirational commands).

Constraints:
- Don’t redesign architecture in this step.
- If commands are stale, mark them clearly and provide replacements.

Deliverables:
- Updated/new runbook markdown.
- Short gap list of ambiguous or missing operational docs.
- Tests/checks run.
```

### Prompt 0.2 — Dockerfile sanity (fix or retire)
```text
Continue Phase 0 from docs/web_ui_evolution_plan.md.

Task:
1) Inspect Dockerfile/container artifacts for stale paths/assumptions.
2) Either:
   A) fix them so image build reflects current repo structure, or
   B) retire/deprecate Dockerfile explicitly in docs if not intended for production.
3) Ensure docs accurately state supported deployment profile(s).

Deliverables:
- Dockerfile/compose/docs changes.
- Rationale for “fixed” vs “retired”.
- Validation command(s) and results.
```

### Prompt 0.3 — Endpoint inventory + concurrency guard
```text
Continue Phase 0 from docs/web_ui_evolution_plan.md.

Task:
1) Inventory API endpoints and classify each as read / command / admin.
2) Commit this inventory in docs (table format).
3) Add an explicit concurrency guard for high-risk operations (sync/plan/deploy-sensitive), minimally invasive to current design.
4) Add/update tests proving guard behavior.

Deliverables:
- Endpoint classification doc.
- Code change implementing guard.
- Tests covering no-overlap behavior.
```

---

## Phase 1 — API hardening for UI consumption (1–2 weeks)

### Prompt 1.1 — Introduce `/api/v1`
```text
I’m implementing Phase 1 of docs/web_ui_evolution_plan.md.

Task:
1) Add `/api/v1` namespace for existing API routes with backward-compatible transition strategy.
2) Keep old routes temporarily if needed, but document deprecation path.
3) Update route tests to cover `/api/v1` equivalents.

Deliverables:
- Router wiring updates.
- Tests for key read endpoints under `/api/v1`.
- Migration note in docs.
```

### Prompt 1.2 — Auth surface tightening for human-facing routes
```text
Continue Phase 1.

Task:
1) Remove API key acceptance through query parameters for human-facing routes.
2) Keep secure header-based mechanism where still needed.
3) Add regression tests ensuring query-param auth is rejected where intended.
4) Update docs/examples accordingly.

Deliverables:
- Auth dependency/middleware updates.
- Tests for rejected query-param auth.
- Updated API usage docs.
```

### Prompt 1.3 — Error schema, correlation IDs, endpoint protections
```text
Continue Phase 1.

Task:
1) Normalize API error response schema across routes.
2) Add/request correlation IDs (generate if absent, return in response headers).
3) Add practical rate limits/timeouts for command endpoints.
4) Add tests for error schema consistency and correlation ID presence.

Deliverables:
- Shared error model/handler.
- Correlation ID middleware/dependency.
- Command endpoint protection changes.
- Test coverage + docs update.
```

---

## Phase 2 — AuthN/AuthZ + internet hardening (2–3 weeks)

### Prompt 2.1 — User/session/RBAC data model
```text
I’m implementing Phase 2 of docs/web_ui_evolution_plan.md.

Task:
1) Add DB schema + migration(s) for users, sessions, and RBAC roles (owner/operator/read_only).
2) Add password hashing utilities and user repository/service layer.
3) Keep current machine API key path intact for non-browser automations.

Deliverables:
- Migration(s).
- Application/infrastructure code for user/session primitives.
- Tests for user creation/auth primitives.
```

### Prompt 2.2 — Login/logout/session cookies + CSRF
```text
Continue Phase 2.

Task:
1) Implement login/logout/session flow for browser users.
2) Set secure cookie flags (HttpOnly, Secure, SameSite policy appropriate to deployment).
3) Add CSRF protection for state-changing browser actions.
4) Add tests for authenticated vs unauthenticated access.

Deliverables:
- Auth routes + middleware/dependencies.
- Session + CSRF enforcement.
- Test coverage.
```

### Prompt 2.3 — Brute-force protections + security headers + CORS
```text
Continue Phase 2.

Task:
1) Add login brute-force protection (rate limit + lockout/backoff).
2) Apply strict CORS and baseline security headers.
3) Ensure machine API keys are scoped to machine endpoints only; document rotation procedure.
4) Add tests for lockout behavior and role-restricted endpoint access.

Deliverables:
- Security middleware/config updates.
- Tests for brute-force and RBAC enforcement.
- Security operations doc update.
```

---

## Phase 3 — Minimal web operator console (2–4 weeks)

### Prompt 3.1 — Web UI skeleton + layout
```text
I’m implementing Phase 3 of docs/web_ui_evolution_plan.md.

Task:
1) Build initial web UI shell (server-rendered templates preferred unless repo already has another standard).
2) Add authenticated navigation + base layout for operator console.
3) Include role-aware nav visibility.

Deliverables:
- Template/static asset structure.
- Base authenticated pages.
- Tests for route auth and render.
```

### Prompt 3.2 — Status/sync/plan/trends/nutrition views
```text
Continue Phase 3.

Task:
Implement web views for:
1) system health/status checks,
2) last sync outcomes with source-level failures,
3) current week plan + decision trace,
4) trend snapshots (weight/sleep/hrv/volume),
5) nutrition daily summary.

Constraints:
- Reuse existing read APIs/services where possible.
- Avoid duplicating business logic in templates/controllers.

Deliverables:
- Route handlers + templates/components.
- Tests for page responses and key rendered states.
```

### Prompt 3.3 — Safe command controls + confirmations
```text
Continue Phase 3.

Task:
1) Add UI actions for run sync, generate plan, resend message.
2) Require explicit confirmation UX for potentially disruptive commands.
3) Ensure commands are RBAC-protected and auditable.
4) Add tests for authorization and confirmation enforcement.

Deliverables:
- Command UI + handlers.
- Audit/event logging hooks.
- Tests.
```

---

## Phase 4 — Observability + operations maturity (1–2 weeks)

### Prompt 4.1 — Structured logs + correlation
```text
I’m implementing Phase 4 of docs/web_ui_evolution_plan.md.

Task:
1) Standardize structured JSON logging across API + background job paths.
2) Include request ID, job ID, user/session identity (where applicable), and outcome fields.
3) Document log schema and local troubleshooting workflow.

Deliverables:
- Logging configuration + adapters.
- Docs for log fields and triage steps.
- Validation checks/tests.
```

### Prompt 4.2 — Metrics and health instrumentation
```text
Continue Phase 4.

Task:
1) Add metrics for job latency, failures, retries, external API health.
2) Expose/update health/readiness endpoints with meaningful dependency checks.
3) Add tests for metrics emission and readiness behavior.

Deliverables:
- Metrics instrumentation.
- Health endpoint updates.
- Tests and scrape/usage notes.
```

### Prompt 4.3 — Alert hooks + failure playbooks
```text
Continue Phase 4.

Task:
1) Add alerting hooks/events for stale ingest, auth expiry, repeated failures.
2) Add/expand operational playbooks for incident diagnosis without shell access.
3) Document severity mapping and response expectations.

Deliverables:
- Alert trigger wiring.
- Playbook docs.
- Tests (unit/integration where feasible).
```

---

## Phase 5 — Extensibility foundations (optional)

### Prompt 5.1 — Adapter/plugin contracts
```text
I’m implementing Phase 5 of docs/web_ui_evolution_plan.md.

Task:
1) Define formal adapter/plugin interfaces for new data providers and notification channels.
2) Refactor one existing provider/channel behind the new interface as reference implementation.
3) Add developer docs for adding a new adapter.

Deliverables:
- Interface definitions.
- One migrated reference adapter.
- Tests + extension guide.
```

### Prompt 5.2 — Feature flags for planner experiments
```text
Continue Phase 5.

Task:
1) Add feature-flag mechanism for experimental planner behaviors.
2) Support safe defaults + explicit override path.
3) Audit-log when non-default flags affect plan generation.
4) Add tests for flag gating behavior.

Deliverables:
- Flag config and evaluation logic.
- Tests.
- Ops doc for enabling/disabling flags.
```

### Prompt 5.3 — Optional multi-profile abstraction
```text
Continue Phase 5.

Task:
1) Introduce optional multi-profile user abstraction while keeping single-user default behavior.
2) Ensure compatibility with existing data and workflows.
3) Add migration/rollback guidance and tests.

Deliverables:
- Model/service updates.
- Backward-compatibility tests.
- Migration notes.
```

---

## Final integration / release prompts

### Prompt R.1 — End-to-end hardening review
```text
Run an end-to-end review of implemented Phases 0–4 (and 5 if present):
1) verify security posture against docs/web_ui_evolution_plan.md,
2) verify daily operator workflows are fully web-possible,
3) list remaining CLI-only break-glass operations,
4) produce prioritized gap list (P0/P1/P2) with effort estimates.

Deliverables:
- Review report in docs/.
- Actionable backlog list.
```

### Prompt R.2 — Production readiness checklist
```text
Create/update a production readiness checklist covering:
- deployment prerequisites,
- TLS/reverse proxy config expectations,
- auth/session/security controls,
- backup/restore validation,
- observability + alert tests,
- rollback plan.

Deliverables:
- Checklist doc + signoff template.
```
