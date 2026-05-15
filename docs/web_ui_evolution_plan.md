# Pete-Eebot Web UI Evolution Plan (Architecture Assessment)

_Date: 2026-05-15_

## Executive summary

Pete-Eebot already has strong fundamentals for incremental evolution into a remotely accessible web application:

- clean-ish layered architecture (`domain` / `application` / `infrastructure` / API routes)
- production-oriented CLI workflows and operational scripts
- Postgres as stable source of truth
- explicit deployment/ops conventions for Raspberry Pi and cron/systemd
- practical security controls (API key gate, webhook signature validation, encrypted cloud backups)

The best path is **evolution, not rewrite**:
1. preserve the current CLI + automation backbone,
2. harden the existing FastAPI surface,
3. add an operator-oriented web UI on top of current read APIs,
4. introduce session-based auth and RBAC-lite,
5. progressively move unsafe imperative endpoints/operations behind job orchestration and auditable controls.

A full redesign is not currently required. Targeted modularisation and platform hardening are the highest-leverage changes.

---

## Current-state architecture analysis

### 1) Repository and module structure

Current structure reflects a layered design:

- `pete_e/domain`: planning, progression, validation, narrative rules.
- `pete_e/application`: orchestration + workflows + service composition.
- `pete_e/infrastructure`: Postgres DAL, external clients, cron/deploy utilities.
- `pete_e/api_routes` + `pete_e/api.py`: HTTP transport.
- `pete_e/cli`: Typer command surfaces.
- `scripts/`: operator tooling (auth checks, backup, cron install, weekly workflows).
- `migrations/` + `init-db/schema.sql`: DB lifecycle.
- `tests/`: layered tests (domain/application/integration/CLI).

This is a solid basis for extension.

### 2) Runtime + deployment model inferred from code/docs

- Primary operating model is CLI + cron/systemd-driven automation.
- Production reference deployment is Raspberry Pi with mutable runtime assets outside git checkout (`.env`, venv, backups).
- Deploy webhook model exists; webhook triggers shell deploy script that updates git checkout, reinstalls app, refreshes cron, restarts service.
- Docker Compose is mainly DB-focused and appears secondary to Pi native deployment.

### 3) API model today

FastAPI app exists and routers are separated by concern (metrics, plans, nutrition, status/sync, logs/webhook). This is already a useful application API skeleton for UI integration.

Auth/security today for API:

- API key required (`PETEEEBOT_API_KEY`) via header or query string.
- Webhook signature required (`X-Hub-Signature-256`) with HMAC SHA256.
- Fails closed when core secrets are unset.

### 4) Data and state model

- Postgres is central source of truth for training plans, metrics, nutrition logs, export history.
- Withings OAuth tokens are persisted locally (`~/.config/pete_eebot/.withings_tokens.json`) with permission hardening flows.
- Backups include DB dumps and secret snapshots; optional encrypted Dropbox upload.

### 5) Design philosophy inferred

- personal production system: reliability and operability matter more than novelty
- pragmatic automation-first approach
- low-resource friendliness (Pi)
- explicit concern separation without over-abstracting

---

## Risks and constraints

### Security risks (remote exposure)

1. **Single shared API key model** is insufficient for browser-facing multi-session access.
2. **API key accepted in query params** raises leakage risk through logs/history/referers.
3. **`subprocess.Popen` endpoints** (`run_pete_plan_async`, webhook deploy) can become remote code execution blast-radius multipliers if perimeter controls fail.
4. No explicit CSRF/session model for browser use.
5. Secrets remain `.env` and local files; workable for Pi local ops, weaker for internet-facing threat model.

### Operational risks

1. Cron + API-triggered operations may overlap (race conditions) without centralized job locking/queueing.
2. Limited built-in observability for web-era operations (no structured request telemetry, traces, explicit SLO signals).
3. Dockerfile appears stale/inconsistent with current repo contents (copies missing paths like `migration.py`, `knowledge`, `integrations`) and should not be treated as production-ready web deploy artifact.

### Architecture constraints

1. Current boundaries are mostly good, but some route handlers directly invoke subprocesses/imperative actions.
2. Existing APIs are practical but not versioned/documented as stable product contracts for web client evolution.
3. Single-user assumptions are embedded in config and workflows; that is fine now but should be explicit for future extensibility.

---

## Recommended architecture

## Guiding principle

**Keep the current core as the domain/application engine; add a thin remote operator platform around it.**

### Target architecture (incremental)

1. **Core engine (unchanged in principle):**
   - domain + application orchestration remains the source of business logic.
   - CLI remains first-class for operations and incident fallback.

2. **Hardened service API layer:**
   - keep FastAPI but formalize into:
     - read APIs (dashboard/metrics/plans)
     - command APIs (sync/run plan/recalibration/deploy hooks)
     - admin APIs (health, logs, config metadata)
   - move command execution through an application command bus or job service instead of raw subprocess route calls.

3. **Web UI (operator console):**
   - a minimal server-rendered or SPA frontend consuming same FastAPI.
   - initial UX: status, latest sync health, plan/week view, readiness trends, recent alerts, config diagnostics.

4. **Auth gateway model:**
   - migrate from single API key to user session auth for browser.
   - retain machine API key for automations/webhooks, scoped and rotated.

5. **Job orchestration & safety rails:**
   - serialized/locked execution for sync/plan/deploy-sensitive tasks.
   - idempotency keys + audit trails for command endpoints.

6. **Observability layer:**
   - structured logs + request IDs.
   - metrics endpoint for service health and job durations.
   - alertable events for failures/staleness/auth expiry.

---

## Recommended technology decisions (with rationale)

## Frontend

- **Decision:** Start with lightweight server-rendered templates (FastAPI + Jinja2) _or_ a minimal SPA only after API contracts stabilize.
- **Rationale:** lowest ops overhead for a single-user production personal system; easier auth/session integration and reduced deployment complexity.

## Backend/API

- **Decision:** Continue with FastAPI; introduce API versioning (`/api/v1`) and OpenAPI discipline.
- **Rationale:** existing investment + tests + route decomposition already align well.

## Auth

- **Decision:** Add session auth (password + TOTP optional) for browser users; keep API key auth only for machine integrations/webhooks.
- **Rationale:** shared API key is not appropriate for remote UI.

## Config/secrets

- **Decision:** Keep `.env` for local/Pi baseline, but add optional secrets provider adapters (Docker secrets / 1Password / Vault / cloud secret manager) behind config abstraction.
- **Rationale:** preserve simplicity while enabling stronger remote-hosted posture.

## Jobs

- **Decision:** Introduce a DB-backed job table + worker loop (can run in same process initially) before adopting external queue infra.
- **Rationale:** incremental reliability improvement without heavy infrastructure.

## Observability

- **Decision:** standard JSON logs + optional Prometheus metrics + health/readiness endpoints.
- **Rationale:** maintainable and simple for both Pi and cloud transitions.

## Deployment

- **Decision:** maintain two supported profiles:
  - **Profile A:** Pi/self-hosted (systemd + reverse proxy + TLS)
  - **Profile B:** containerized VM/cloud single-instance (managed Postgres optional)
- **Rationale:** avoid forced migration while enabling future portability.

---

## Phased implementation roadmap

## Phase 0 — Stabilize baseline (1–2 weeks)

- Document current runtime topology and commands as source-of-truth runbook.
- Fix/retire stale Dockerfile path assumptions.
- Inventory and classify endpoints as read/command/admin.
- Add explicit concurrency guard for high-risk operations (sync/plan/deploy).

Exit criteria:
- Known-good baseline deploy path(s) with smoke checks.

## Phase 1 — API hardening for UI consumption (1–2 weeks)

- Introduce `/api/v1` namespace and contract tests for key read endpoints.
- Remove query-param API key acceptance for human-facing routes.
- Normalize error schema and correlation IDs.
- Add rate limits/timeouts on command endpoints.

Exit criteria:
- Stable read APIs for dashboard and plan views.

## Phase 2 — Authentication and session model (1–2 weeks)

- Implement user table + credential storage (single-user supported, extensible).
- Add login/logout/session cookie, secure flags, CSRF protection.
- Keep existing API key for automation, but scope and rotate.

Exit criteria:
- Browser access requires authenticated session.

## Phase 3 — Minimal web operator console (2–4 weeks)

- Deliver pages for:
  - system health/status checks
  - last sync outcomes + source-level failures
  - current week plan and decision trace view
  - trend snapshots (weight/sleep/hrv/volume)
  - nutrition daily summary
- Add safe command controls with confirmation flows (run sync, generate plan, resend message).

Exit criteria:
- Daily operator workflows possible entirely via web UI while CLI remains available.

## Phase 4 — Observability and operations maturity (1–2 weeks)

- Structured logs with request/job correlation IDs.
- Metrics for job latency, failures, external API health.
- Alerting hooks for stale ingest, auth expiry, repeated failures.

Exit criteria:
- Fast incident diagnosis without shell access.

## Phase 5 — Extensibility foundations (optional)

- Formal plugin/adapter contracts for new data providers or notification channels.
- Feature flags for experimental planner behaviors.
- Optional multi-profile user abstraction (still single-user default).

Exit criteria:
- controlled extension without architecture churn.

---

## Security model

### Near-term

- Keep webhook HMAC validation.
- Enforce HTTPS-only ingress (reverse proxy + cert automation).
- Remove API key in query string for UI calls.
- Add secure cookie sessions, CSRF protection, same-site policy.
- Restrict command endpoints behind stronger auth + explicit audit logging.

### Medium-term

- Secret rotation policy for API keys, bot tokens, OAuth creds.
- Optional TOTP/MFA for admin login.
- Principle-of-least-privilege process user and filesystem perms.
- Network boundary: private LAN/VPN-first exposure for Pi; no raw public port.

### Command safety

- replace direct subprocess route invocations with queued commands + allowlist.
- job-level locking for plan generation/sync/deploy-sensitive tasks.

---

## Deployment model

### Self-hosted Pi (recommended immediate)

- Keep existing systemd + cron model.
- Front with Caddy/Nginx for TLS and auth-aware proxy headers.
- Run FastAPI (uvicorn/gunicorn) bound localhost; proxy from 443.
- Maintain current backup strategy (encrypted cloud option).

### Cloud single-instance (future)

- Containerized app + managed Postgres.
- Secret manager instead of plain `.env` where feasible.
- Scheduled jobs via platform scheduler or in-app worker.
- Same codebase and core workflows, minimal branching.

---

## Operational considerations

- **Do not remove CLI workflows.** They are resilient fallback controls.
- Keep cron-based automation until job system proves stable; then progressively consolidate.
- Add recovery playbooks for:
  - OAuth expiry/re-auth
  - DB restore
  - failed deploy rollback
  - missed sync windows
- Maintain compatibility with low-resource hosts; avoid infra-heavy additions unless justified by concrete pain.

---

## Open questions / assumptions

1. Is remote access intended over public internet, VPN-only, or LAN-only?
2. Is there any requirement for multi-user access within 12 months?
3. Which operations are acceptable from UI vs CLI-only (e.g., deploy trigger)?
4. Preferred trust boundary for secrets (local files vs external manager)?
5. Is zero-downtime deploy required, or brief maintenance windows acceptable?
6. Is the stale Dockerfile still used anywhere operationally, or can it be safely replaced?

---

## Final recommendation

Adopt an **incremental “harden-and-wrap” strategy**:

- preserve the current core architecture and automation philosophy,
- harden APIs/auth for remote browser use,
- add a minimal operator web console on top of existing services,
- introduce command/job safety and observability,
- keep Pi-first operational simplicity while enabling a cloud-ready path.

This delivers secure remote usability and better operational confidence without risking regressions from a wholesale rewrite.
