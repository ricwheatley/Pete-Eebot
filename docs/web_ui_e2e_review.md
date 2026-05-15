# Web UI End-to-End Review

Date: 2026-05-15

Scope: implemented Phases 0-4 from `docs/web_ui_evolution_plan.md`, plus Phase 5 items present in this repo.

## Executive Summary

The implementation covers most of the planned foundation: `/api/v1` exists, browser sessions and RBAC are in place, command endpoints have CSRF/rate-limit/confirmation controls, the operator console renders the required status/plan/trends/nutrition views, and observability now includes structured logs, correlation IDs, Prometheus-style metrics, and alert hooks.

The main review result is: **security posture is materially improved, but the Phase 3 exit criterion is not fully met yet.** Daily web operation is possible for status, all-source sync, current plan review, trend review, nutrition summary, and message resend. It is not yet fully web-possible for source-specific ingest, morning report preview/send, OAuth recovery, a first-class log viewer, or weekly review/strength-test lifecycle commands.

The highest-priority production gaps are:

- Browser auth has no documented or callable owner bootstrap path, and no password reset/recovery flow.
- Several console operations still start raw CLI subprocesses rather than durable, inspectable jobs.
- The console lacks a Logs page even though incident playbooks refer to console-based log triage.

## Phase Completion Snapshot

| Phase | Target | Review result | Evidence |
| --- | --- | --- | --- |
| Phase 0 | Runtime docs, retired stale Dockerfile, endpoint inventory, concurrency guard | Mostly complete | `docs/runtime_deploy_runbook.md`, `docs/api_endpoint_inventory.md`, `pete_e/application/concurrency_guard.py`, guarded sync/plan/deploy paths |
| Phase 1 | `/api/v1`, no query API keys, error envelope, correlation IDs, command protections | Complete for reviewed surface | `pete_e/api.py`, `pete_e/api_errors.py`, `pete_e/api_routes/dependencies.py`, `tests/test_api_auth.py`, `tests/test_api_hardening.py` |
| Phase 2 | User/session/RBAC, cookies, CSRF, brute force controls, CORS, security headers | Mostly complete, recovery/bootstrap gaps remain | `migrations/20260515_add_auth_users_sessions_rbac.sql`, `pete_e/api_routes/auth.py`, `pete_e/api_security.py`, `tests/test_browser_auth.py` |
| Phase 3 | Minimal web console and daily operator workflows via web | Partially complete | `pete_e/api_routes/web.py`, `pete_e/application/web_console.py`, templates under `pete_e/templates/console`, `tests/test_web_console.py` |
| Phase 4 | Structured logs, metrics, readiness, alerts, playbooks | Mostly complete, UI integration gap remains | `pete_e/api_logging.py`, `pete_e/observability.py`, `pete_e/application/alerts.py`, `docs/logging_observability.md`, `docs/runtime_deploy_runbook.md` |
| Phase 5 | Optional adapter contracts, feature flags, multi-profile foundation | Present as foundation | `pete_e/application/adapter_contracts.py`, `docs/adapter_extension_guide.md`, `docs/planner_feature_flags.md`, `docs/multi_profile_migration_note.md` |

## Security Posture Review

| Control from plan | Status | Notes |
| --- | --- | --- |
| Keep API keys out of query strings | Pass | `validate_api_key` ignores query param keys and tests cover rejection. |
| `/api/v1` stable API namespace | Pass | Versioned and legacy routes are mounted; legacy deprecation is documented. |
| Browser sessions instead of shared API key | Pass | Login/session/logout routes exist with hashed session tokens and DB-backed sessions. |
| RBAC roles: `owner`, `operator`, `read_only` | Pass | Role tables, service model, nav visibility, and command enforcement exist. |
| CSRF for browser state changes | Pass | Session state-changing requests require `X-CSRF-Token` matching readable CSRF cookie. |
| Secure cookie flags | Partial | HttpOnly session and SameSite/Secure controls exist. Production safety depends on environment values. |
| Brute force protection | Pass with caveat | In-process backoff/lockout exists. It resets on process restart and is not distributed. |
| Strict CORS and security headers | Pass with caveat | CORS is explicit allowlist only; baseline headers exist. CSP is basic but suitable for the current same-origin app. |
| Machine API keys scoped to machine endpoints | Pass | Browser auth routes reject API key auth; documented machine path allowlist exists. |
| Webhook HMAC validation | Pass | GitHub webhook validates `X-Hub-Signature-256`. |
| Command endpoint safety | Partial | Commands are allowlisted, RBAC/CSRF protected, rate-limited, confirmed, audited, and guarded. Plan/deploy/message still execute direct subprocesses. |
| Job-level locking | Partial | Process-local guard exists. It is not DB-backed and does not coordinate across multiple API processes or cron. |
| Audit trails | Partial | Structured audit logs exist. There is no durable DB audit/job table or console audit view. |
| Password reset flow | Missing | Required by Phase 2 prompt/plan; no route, CLI, or doc path found. |
| Admin/user management UI | Missing | `/console/admin` is a placeholder only. |
| Public-internet deployment binding | Pass | `docs/runtime_deploy_runbook.md` now documents localhost app binding behind reverse proxy/TLS/firewall, with production readiness gates in `docs/production_readiness_checklist.md`. |

## Daily Operator Workflow Review

| Workflow | Web status | Current web/API path | Gap |
| --- | --- | --- | --- |
| Sign in/out | Web possible | `/login`, `/auth/login`, `/auth/logout` | Owner bootstrap/recovery is not documented. |
| Health checks | Web possible | `/console/status`, `/api/v1/status`, `/readyz` | `/readyz` exposes detailed dependency status unauthenticated unless the reverse proxy restricts it. |
| Last sync outcome and source failures | Web possible | `/console/status` | Good enough for daily triage. |
| View current week plan | Web possible | `/console/plan`, `/api/v1/plan_for_week` | Good enough for daily review. |
| View decision trace | Web possible | `/console/plan`, `/api/v1/plan_decision_trace` | Good enough for daily review. |
| View readiness/trends | Web possible | `/console/trends`, coach-state APIs | Good enough for daily review. |
| View nutrition summary | Web possible | `/console/nutrition`, `/api/v1/nutrition/daily-summary` | Console is read-only. |
| Log or edit macros | API possible, not console possible | `POST/PATCH /api/v1/nutrition/log-macros` | Add console forms if human operators need this outside GPT/action clients. |
| Run standard all-source sync | Web possible | `/console/operations/run-sync`, `/api/v1/sync` | Good enough for daily remediation. |
| Run Withings-only sync | CLI-only | `pete withings-sync` | No web command. |
| Run Apple-only ingest | CLI-only | `pete ingest-apple` | No web command. |
| Generate/send daily summary | Partial | `/console/operations/resend-message` with `summary` | No preview, no date override, does not expose `pete morning-report`. |
| Generate/send trainer message | Web possible | `/console/operations/resend-message` with `trainer` | No preview. |
| View recent logs | API possible, not console possible | `/api/v1/logs?lines=N` | Runbook references console Logs, but no Logs nav/page exists. |
| Run weekly plan message resend | Web possible | `/console/operations/resend-message` with `plan` | No preview. |
| Generate next plan block | Web possible | `/console/operations/generate-plan`, `/api/v1/run_pete_plan_async` | Starts subprocess and has no job status page. |

Daily operator workflows are therefore **partially web-possible**. The normal read-and-remediate loop is covered, but there are still routine or near-routine paths that require CLI/shell access.

## Remaining CLI-Only Break-Glass Operations

These should remain CLI/shell-only unless there is a strong product reason to move them into the console:

- Database bootstrap and migrations: `psql "$DATABASE_URL" -f init-db/schema.sql`, `psql ... migrations/*.sql`.
- Backup and restore: `scripts/backup_db.sh`, `pg_restore`, decrypting cloud backup artifacts.
- Secret rotation and environment edits: `.env`, API key, bot token, OAuth credentials, Dropbox refresh token, backup encryption keys.
- Service management: `systemctl restart peteeebot.service`, heartbeat checks, reverse proxy changes.
- Git/deploy recovery: failed deploy inspection, rollback, manual `deploy.sh` runs.
- Cron installation and repair: `pete_e.infrastructure.cron_manager`, `scripts/install_cron_examples.sh`.
- Withings OAuth recovery: `pete withings-auth`, `pete withings-code`, `pete refresh-withings`.
- wger catalog refresh and ingredient/export utilities: `python -m scripts.sync_wger_catalog`, Postman collection flows, exporter scripts.
- Manual SQL plan surgery: training max edits, assistance/core pool edits, active-plan workout inserts/deletes, materialized view refreshes.
- Main lift/system rule changes: code edits in `pete_e/domain/schedule_rules.py`, `PlanFactory`, and SQL function updates.
- Telegram listener offset repair and scheduler troubleshooting.
- Process-output diagnosis for failed plan/message/deploy subprocesses.

These should move into web only if the operation becomes routine, can be safely modeled with typed inputs, and has durable audit/job state.

## Prioritized Gap List

### P0

| Gap | Why it matters | Estimate |
| --- | --- | --- |
| Add owner bootstrap/recovery procedure | The auth tables exist, but there is no documented or callable way to create the first owner or recover access without ad hoc code/SQL. | 1-2 days |
| Add a first-class Logs console page | Incident playbooks reference console log triage, but the UI has no Logs page. Operators must call API/CLI manually. | 1-2 days |

### P1

| Gap | Why it matters | Estimate |
| --- | --- | --- |
| Replace CLI subprocess commands with an application job service for plan/message/deploy | Current controls reduce risk but do not provide durable job status, stdout/stderr capture, or multi-process coordination. | 4-8 days |
| Add password reset or owner-driven password recovery | Phase 2 requested reset flow. Without it, routine auth recovery is a shell/SQL break-glass operation. | 2-4 days |
| Add web source-specific ingest actions | Withings-only and Apple-only paths are common remediation workflows but remain CLI-only. | 2-3 days |
| Add morning-report preview/send command | The scheduler runs `pete morning-report --send`, but console only resends `pete message --summary`. | 1-2 days |
| Add weekly review and strength-test lifecycle commands | `scripts.run_sunday_review` and `pete lets-begin` are weekly/cycle operations with no web surface. | 3-5 days |
| Add durable audit/job history storage | Logs are useful but not queryable product state; in-memory metrics reset on restart. | 4-7 days |
| Restrict or redact unauthenticated readiness details | `/readyz` is unauthenticated and returns dependency details. Safe if reverse-proxy restricted, leaky if public. | 0.5-1 day |

### P2

| Gap | Why it matters | Estimate |
| --- | --- | --- |
| Add nutrition log/edit forms to console | API exists, but human operator nutrition writes are not console-native. | 2-4 days |
| Build real admin user/role management UI | `/console/admin` is a placeholder. | 3-6 days |
| Add optional MFA/TOTP for owner/operator users | Medium-term security model calls this out; not required for initial single-user rollout. | 3-5 days |
| Add UI for alert history and active alerts | Alerts exist in logs/metrics/Telegram but are not a console view. | 2-4 days |
| Add web-visible cron/scheduler status | Scheduler failures are diagnosed through status/logs rather than a dedicated schedule page. | 2-3 days |
| Add web docs/help links for break-glass flows | Keeps dangerous operations out of UI while making escalation paths clear. | 1 day |

## Release Recommendation

Do not treat Phases 0-4 as fully closed until the P0 items are complete. After that, the system is reasonable for a controlled single-operator web rollout behind TLS/reverse proxy, with CLI retained for break-glass and cycle-level operations. Phase 3 should remain open until the P1 daily/weekly workflow gaps are either implemented or explicitly reclassified as break-glass.
