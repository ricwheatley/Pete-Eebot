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
1. preserve the current domain/application core while transitioning production operations to web-driven workflows,
2. harden the existing FastAPI surface for public-internet exposure,
3. add a production-grade web UI as the primary operator surface,
4. introduce session-based auth with multi-user RBAC from day one,
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

- API key required (`PETEEEBOT_API_KEY`) via the `X-API-Key` header. Query-string API-key auth was removed in Phase 1.
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
2. **API key in query params** is rejected after Phase 1 because it raises leakage risk through logs/history/referrers.
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
3. Single-user assumptions are currently embedded in config/workflows, but future near-term multi-user support requires elevating identity/authorization boundaries early.

---

## Recommended architecture

## Guiding principle

**Keep the current core as the domain/application engine; add a thin remote operator platform around it.**

### Target architecture (incremental)

1. **Core engine (unchanged in principle):**
   - domain + application orchestration remains the source of business logic.
   - CLI becomes a development/testing tool; production user operations move to web UI and background jobs.

2. **Hardened service API layer:**
   - keep FastAPI but formalize into:
     - read APIs (dashboard/metrics/plans)
     - command APIs (sync/run plan/recalibration/deploy hooks)
     - admin APIs (health, logs, config metadata)
   - move command execution through an application command bus or job service instead of raw subprocess route calls.

3. **Web UI (operator console):**
   - a minimal server-rendered or SPA frontend consuming same FastAPI.
   - initial UX: status, latest sync health, plan/week view, readiness trends, recent alerts, config diagnostics, and authenticated command actions.

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

- **Decision:** Start with server-rendered templates (FastAPI + Jinja2) as the first production UI, then evaluate SPA only if interaction complexity grows.
- **Rationale:** lowest operational burden for public-internet hosting while still supporting fast iteration and robust session security.

## Backend/API

- **Decision:** Continue with FastAPI; introduce API versioning (`/api/v1`) and OpenAPI discipline.
- **Rationale:** existing investment + tests + route decomposition already align well.

## Auth

- **Decision:** Add multi-user session auth (email/username + password, optional TOTP) with RBAC roles (`owner`, `operator`, `read_only`) and per-user audit trails.
- **Rationale:** public internet exposure and 12-month multi-user needs require identity-based controls, not shared secrets.

## Config/secrets

- **Decision:** Keep local-file secrets initially (`.env` + strict file permissions), with optional free secrets migration path later (e.g., SOPS+age in private repo or self-hosted Vaultwarden/Bitwarden if desired).
- **Rationale:** avoids recurring cost while still improving operational hygiene.

## Jobs

- **Decision:** Introduce a DB-backed job table + worker loop (can run in same process initially) before adopting external queue infra.
- **Rationale:** incremental reliability improvement without heavy infrastructure.

## Observability

- **Decision:** standard JSON logs + optional Prometheus metrics + health/readiness endpoints.
- **Rationale:** maintainable and simple for both Pi and cloud transitions.

## Deployment

- **Decision:** maintain one supported production profile now and one future target profile:
  - **Current supported profile (primary):** native Python virtual environment on an internet-exposed self-hosted VM/Pi behind reverse proxy + TLS + firewall.
  - **Future target profile:** containerized single-instance host with optional managed services, after a fresh application Dockerfile is designed and validated.
- **Rationale:** supports immediate public-internet target without over-complicating ops.

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

## Phase 2 — Authentication, authorization, and internet hardening (2–3 weeks)

- Implement user/auth tables, hashed passwords, session store, and RBAC roles.
- Add login/logout/session cookie, secure flags, CSRF protection, password reset flow.
- Add brute-force protections (rate limit + lockout/backoff), strict CORS, and security headers.
- Keep API keys only for machine actors (webhook/internal jobs), scope and rotate.

Exit criteria:
- Browser access requires authenticated user sessions with role-based authorization.

## Phase 3 — Minimal web operator console (2–4 weeks)

- Deliver pages for:
  - system health/status checks
  - last sync outcomes + source-level failures
  - current week plan and decision trace view
  - trend snapshots (weight/sleep/hrv/volume)
  - nutrition daily summary
- Add safe command controls with confirmation flows (run sync, generate plan, resend message).

Exit criteria:
- Daily operator workflows possible entirely via web UI; CLI retained only for dev/test and emergency break-glass ops.

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
- Keep API keys out of query strings for all UI/API calls.
- Add secure cookie sessions, CSRF protection, same-site policy.
- Restrict command endpoints behind stronger auth + explicit audit logging.

### Medium-term

- Secret rotation policy for API keys, bot tokens, OAuth creds.
- Optional TOTP/MFA for admin login.
- Principle-of-least-privilege process user and filesystem perms.
- Network boundary: public internet exposure behind reverse proxy/WAF-style controls, firewall allowlists where possible, no direct app port exposure.

### Command safety

- replace direct subprocess route invocations with queued commands + allowlist.
- job-level locking for plan generation/sync/deploy-sensitive tasks.

---

## Deployment model

### Public-internet self-hosted (recommended immediate)

- Keep systemd service management with controlled maintenance windows.
- Front with Caddy/Nginx on 443 with automatic TLS, HSTS, and request size/time limits.
- Bind FastAPI to localhost only; expose only reverse proxy.
- Maintain encrypted backup strategy and test restore quarterly.

### Cloud single-instance (future, optional; not currently supported)

- Containerized app + managed Postgres.
- Secret manager instead of plain `.env` where feasible.
- Scheduled jobs via platform scheduler or in-app worker.
- Same codebase and core workflows, minimal branching.

---

## Operational considerations

- Production UX should be web-first; CLI retained for development/testing and controlled break-glass recovery only.
- Keep cron-based automation until job system proves stable; then progressively consolidate.
- Add recovery playbooks for:
  - OAuth expiry/re-auth
  - DB restore
  - failed deploy rollback
  - missed sync windows
- Maintain compatibility with low-resource hosts; avoid infra-heavy additions unless justified by concrete pain.

---

## Confirmed assumptions (from product direction)

1. Remote access target: **public internet**.
2. Multi-user requirement: **yes, within 12 months**.
3. Production surface target: **web UI primary**; CLI should be dev/test only.
4. Secrets boundary: **local/free-first** (no mandatory paid secret manager).
5. Deploy SLO: **brief maintenance windows acceptable** (no strict zero-downtime requirement).
6. Legacy Dockerfile: **unused** and retired on 2026-05-15; `docker-compose.yml` is currently DB-only.

---

## Final recommendation

Adopt an **incremental “harden-and-wrap” strategy**:

- preserve the current core architecture and automation philosophy,
- harden APIs/auth for remote browser use,
- add a minimal operator web console on top of existing services,
- introduce command/job safety and observability,
- keep Pi-first operational simplicity while enabling a cloud-ready path.

This delivers secure remote usability and better operational confidence without risking regressions from a wholesale rewrite.
