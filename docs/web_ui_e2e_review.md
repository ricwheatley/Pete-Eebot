# Web UI End-to-End Review

Date: 2026-05-16

Scope: implemented Phases 0-4 from `docs/web_ui_evolution_plan.md`, Phase 5 foundations, and the latest console hardening/user-workflow additions.

## Executive Summary

The web console now covers the normal single-operator operating loop: authenticated status, plan, trends, nutrition summary and nutrition writes, logs, alert history, scheduler status, durable jobs, command history, operational commands, MFA enrollment, and owner user/role administration.

Security posture is materially stronger than the earlier review. Browser sessions, CSRF, RBAC, command confirmations, durable job/audit records, owner-managed users, and optional MFA are implemented. Dangerous break-glass flows remain reference-only links to the runbook; the browser does not execute OAuth recovery, backup/restore, migration, cron repair, or service restart commands.

The remaining release caveats are mostly operational maturity issues: some command paths still enqueue subprocesses, alert history is derived from recent structured logs rather than a dedicated alert table, and cron freshness is visible as expected configuration with missing-target checks rather than verified last-run timestamps for every scheduler entry.

## Phase Completion Snapshot

| Phase | Target | Review result | Evidence |
| --- | --- | --- | --- |
| Phase 0 | Runtime docs, retired stale Dockerfile, endpoint inventory, concurrency guard | Mostly complete | `docs/runtime_deploy_runbook.md`, `docs/api_endpoint_inventory.md`, `pete_e/application/concurrency_guard.py`, guarded sync/plan/deploy paths |
| Phase 1 | `/api/v1`, no query API keys, error envelope, correlation IDs, command protections | Complete for reviewed surface | `pete_e/api.py`, `pete_e/api_errors.py`, `pete_e/api_routes/dependencies.py`, API hardening tests |
| Phase 2 | User/session/RBAC, cookies, CSRF, brute force controls, CORS, security headers, optional MFA | Mostly complete | `pete_e/api_routes/auth.py`, `pete_e/application/user_service.py`, auth migrations, browser auth tests |
| Phase 3 | Minimal web console and daily operator workflows via web | Mostly complete | `pete_e/api_routes/web.py`, `pete_e/application/web_console.py`, console templates, `tests/test_web_console.py` |
| Phase 4 | Structured logs, metrics, readiness, alerts, playbooks | Mostly complete | `pete_e/observability.py`, `pete_e/application/alerts.py`, `/console/logs`, `/console/alerts`, `/console/scheduler` |
| Phase 5 | Optional adapter contracts, feature flags, multi-profile foundation | Present as foundation | adapter contracts, planner flags, multi-profile docs |

## Security Posture Review

| Control from plan | Status | Notes |
| --- | --- | --- |
| Keep API keys out of query strings | Pass | Header/session auth only for reviewed paths. |
| Browser sessions instead of shared API key | Pass | Login/session/logout routes use hashed session tokens and DB-backed sessions. |
| RBAC roles: `owner`, `operator`, `read_only` | Pass | Nav, pages, commands, nutrition writes, admin, alerts, scheduler, and MFA are role-gated. |
| CSRF for browser state changes | Pass | Mutation forms call session endpoints with CSRF. |
| Owner user/role management | Pass | `/console/admin` lists users, creates users, updates roles, deactivates users, and can reset MFA. |
| Optional MFA/TOTP | Pass | Owner/operator users can enroll TOTP; enrolled users receive a login challenge; recovery codes and owner reset exist. |
| Command endpoint safety | Mostly pass | Commands are allowlisted, RBAC/CSRF protected, rate-limited, confirmed where destructive, audited, and job-tracked. Some commands still run subprocesses by design. |
| Audit trails | Pass with caveat | Durable command history exists; alert history remains log-derived. |
| Break-glass operations | Pass | Console links to runbook sections but does not execute shell-only recovery flows. |

## Workflow Table

| Workflow | Web status | Current web/API path | Notes |
| --- | --- | --- | --- |
| Sign in/out | Web possible | `/login`, `/auth/login`, `/auth/logout` | MFA challenge appears when enrolled. |
| Owner user management | Web possible | `/console/admin` | Create users, assign roles, deactivate, reset MFA. |
| Health and source freshness | Web possible | `/console/status` | Detailed dependency state remains authenticated. |
| Current plan and decision trace | Web possible | `/console/plan` | Good for daily review. |
| Trends/readiness | Web possible | `/console/trends` | Includes chart controls. |
| View nutrition summary | Web possible | `/console/nutrition` | Read-only users can view. |
| Log/edit macros | Web possible | `/console/nutrition` | Operator/owner forms reuse nutrition service validation and refresh the page after success. |
| Logs and command history | Web possible | `/console/logs`, `/console/history` | Logs are file-backed; command history is durable. |
| Active/recent alerts | Web possible | `/console/alerts` | Severity/type filtering, log-derived active/recent rows. |
| Scheduler status | Web possible | `/console/scheduler` | Shows expected cron entries and missing module targets where detectable. |
| Operational commands | Web possible | `/console/operations` | Sync, Withings, Apple, plan, weekly review, strength-test start, message preview/resend, morning report, deploy owner command. |
| Break-glass recovery references | Web possible | Operations/Admin/Scheduler links | Reference-only links for OAuth, backup/restore, migrations, cron repair, and service restart. |

## Prioritized Gap List

### P0

No current P0 web-console release blockers remain for controlled single-operator rollout behind TLS/reverse proxy.

### P1

| Gap | Why it matters | Estimate |
| --- | --- | --- |
| Replace remaining subprocess-backed commands with direct application job callbacks where practical | Reduces shell/process coupling and improves typed result handling. | 4-8 days |
| Add DB-backed alert records | Alert UI currently reads recent structured logs, which is sufficient for triage but not durable product state. | 2-4 days |
| Add scheduler last-run/freshness tracking | Current scheduler view shows expected config and detectable missing targets, not authoritative execution freshness per cron entry. | 2-4 days |

### P2

| Gap | Why it matters | Estimate |
| --- | --- | --- |
| Make MFA reset/recovery UX richer | Owner reset exists; self-service regeneration of recovery codes would improve routine support. | 1-2 days |
| Add browser-native owner password reset for non-current users | Local reset command exists; admin UI does not yet set passwords after account creation. | 2-3 days |
| Add durable indexed log storage | `/console/logs` is useful but still file-backed. | 4-7 days |

## Release Recommendation

The system is now reasonable for controlled web rollout behind the documented reverse-proxy/TLS/firewall setup. Keep CLI/shell access for break-glass operations and continue treating backup/restore, migrations, OAuth credential repair, cron installation, and service restart as runbook-driven operator actions rather than browser-executed commands.
