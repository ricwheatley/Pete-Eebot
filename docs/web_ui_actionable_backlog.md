# Web UI Actionable Backlog

Date: 2026-05-16

Source review: `docs/web_ui_e2e_review.md`.

## P0

### WEB-P0-001 - Align production binding with reverse-proxy security model

Estimate: 0.5-1 day

Acceptance criteria:

- `docs/runtime_deploy_runbook.md` production command binds Uvicorn to `127.0.0.1` unless explicitly documenting a private-network-only exception.
- Runbook includes TLS reverse proxy expectations: HTTPS, HSTS, request size/time limits, firewall/no direct app-port exposure.
- Smoke checks cover both local app health and public HTTPS health through proxy.

### WEB-P0-002 - Add first-owner bootstrap and recovery procedure

Estimate: 1-2 days

Status: Implemented on 2026-05-15 with local-only `pete bootstrap-owner`
and `pete reset-owner-password` commands. See
`docs/runtime_deploy_runbook.md` section 7.2.

Acceptance criteria:

- [x] A documented supported path exists to create the first `owner` user.
- [x] The path does not require hand-writing password hashes.
- [x] Tests cover creating an owner and rejecting duplicate usernames/emails.
- [x] Recovery instructions exist for a lost owner password or locked account.

### WEB-P0-003 - Add Logs page to operator console

Estimate: 1-2 days

Status: Implemented on 2026-05-15 with `/console/logs`, read-only RBAC,
recent line count, tag/outcome filters, and request/job correlation columns.

Acceptance criteria:

- [x] `/console/logs` is visible to authenticated users.
- [x] Page supports recent line count and basic tag/outcome filtering.
- [x] Log output includes request ID, job ID, level, tag, outcome, and message where present.
- [x] Existing incident playbooks point to the page instead of a non-existent console Logs view.

## P1

### WEB-P1-001 - Introduce durable job service for web commands

Estimate: 4-8 days

Acceptance criteria:

- Sync, plan generation, message resend, and deploy-sensitive commands create durable job records.
- Job records include operation, requester, status, timestamps, request/correlation ID, result summary, and failure reason.
- Console can show current and recent jobs.
- Existing process-local guard is either replaced by or backed by a DB lock so cron/API/multiple-process overlap is controlled.

### WEB-P1-002 - Implement password reset or owner-driven password recovery

Estimate: 2-4 days

Status: Implemented on 2026-05-15 as a local-only owner recovery command. A
browser-native owner/user management UI remains a future enhancement.

Acceptance criteria:

- [x] Owner can reset another user's password or a documented single-host recovery command exists.
- [x] Reset flow revokes existing sessions for the affected user.
- [x] Audit log records reset events without logging secrets.
- [x] Tests cover reset authorization and session revocation.

### WEB-P1-003 - Add source-specific ingest commands

Estimate: 2-3 days

Acceptance criteria:

- Console operations include Withings-only sync and Apple-only ingest.
- Commands require operator/owner role, CSRF token, and typed confirmation.
- Commands reuse application services rather than adding template/controller business logic.
- Results show source-level success/failure and are audit logged.

### WEB-P1-004 - Add morning-report preview/send

Estimate: 1-2 days

Status: Implemented on 2026-05-16 with `/console/operations/morning-report-preview`
and `/console/operations/morning-report-send`.

Acceptance criteria:

- [x] Console can generate the current morning report without sending it.
- [x] Operator can send the generated report with confirmation.
- [x] Optional date override is supported.
- [x] Failures include a request/job ID visible to the operator.

### WEB-P1-005 - Add weekly review and strength-test lifecycle controls

Estimate: 3-5 days

Status: Implemented on 2026-05-16 with confirmed `/console/operations/run-sunday-review`
and `/console/operations/lets-begin` commands.

Acceptance criteria:

- [x] Console can run Sunday review through a confirmed operator command.
- [x] Console can start the strength-test week (`lets-begin`) with explicit start date confirmation.
- [x] Both commands are guarded against overlap with sync/plan/deploy-sensitive work.
- [x] Tests cover authorization, confirmation, invalid date handling, and audit outcomes.

### WEB-P1-006 - Add durable audit/job history

Estimate: 4-7 days

Acceptance criteria:

- Operator command audit events are persisted in DB or another durable store.
- Console exposes searchable recent command history.
- Records link request ID, job ID, user, auth scheme, command, outcome, and safe summary.
- Existing structured log audit remains as a secondary diagnostic stream.

### WEB-P1-007 - Redact or restrict unauthenticated readiness details

Estimate: 0.5-1 day

Acceptance criteria:

- Public unauthenticated readiness returns only coarse status, or docs/proxy config clearly restrict it to local/probe callers.
- Detailed dependency names/errors remain available through authenticated `/api/v1/status` and `/console/status`.
- Tests cover healthy and unhealthy readiness responses.

## P2

### WEB-P2-001 - Add nutrition log/edit forms

Estimate: 2-4 days

Status: Implemented on 2026-05-16 with operator/owner create/edit forms on
`/console/nutrition`, CSRF-protected console endpoints, existing nutrition
service validation, and page refresh after successful writes.

Acceptance criteria:

- [x] Operator/owner users can add and edit nutrition logs from `/console/nutrition`.
- [x] Read-only users cannot see mutation controls.
- [x] Forms use CSRF and existing nutrition service validation.
- [x] Summary refreshes after successful changes.

### WEB-P2-002 - Build admin user and role management

Estimate: 3-6 days

Status: Implemented on 2026-05-16 with `/console/admin`, owner-only user
listing, user creation, role assignment, deactivation, MFA reset, and command
audit events.

Acceptance criteria:

- [x] `/console/admin` lists users and roles for owners.
- [x] Owner can create, deactivate, and assign roles.
- [x] Non-owner users receive `403`.
- [x] All changes are audit logged.

### WEB-P2-003 - Add optional MFA/TOTP

Estimate: 3-5 days

Status: Implemented on 2026-05-16 with TOTP enrollment for owner/operator
users, login challenge when MFA is enabled, recovery codes, and owner reset.

Acceptance criteria:

- [x] Owner/operator users can enroll TOTP.
- [x] Login requires TOTP when enrolled.
- [x] Recovery codes or owner reset path exists.
- [x] Tests cover enabled and disabled MFA paths.

### WEB-P2-004 - Add alert history view

Estimate: 2-4 days

Status: Implemented on 2026-05-16 with `/console/alerts`, operator/owner RBAC,
severity/type filters, and active/recent rows derived from structured alert logs.

Acceptance criteria:

- [x] Console shows active/recent alerts with severity, type, timestamp, and summary.
- [x] Alerts can be filtered by severity/type.
- [x] View links to relevant status/log/job details where available.

### WEB-P2-005 - Add scheduler status view

Estimate: 2-3 days

Status: Implemented on 2026-05-16 with `/console/scheduler`, expected cron
entries from `pete_e/resources/pete_crontab.csv`, missing module-target
highlighting, and runbook repair links.

Acceptance criteria:

- [x] Console shows expected cron entries or scheduler configuration summary.
- [x] It highlights stale/missing recent scheduled runs when data is available.
- [x] It links to runbook break-glass scheduler repair steps.

### WEB-P2-006 - Add break-glass reference links in console

Estimate: 1 day

Status: Implemented on 2026-05-16 with role-gated reference links on
Operations/Admin/Scheduler. The browser does not execute shell commands for
these flows.

Acceptance criteria:

- [x] Operations/Admin pages link to relevant runbook sections for OAuth recovery, backup/restore, migrations, cron repair, and service restart.
- [x] Links are visible only to operator/owner roles.
- [x] No dangerous shell commands are executed by the browser for these flows.
