Add a console workflow for morning report preview and send, matching the existing pete morning-report behavior as closely as practical. Support generating the current report without sending, protected send with confirmation, optional date override if supported by the underlying command, visible request/job IDs on failure, tests, and docs updates.

Add preview support for existing console message resend flows where practical: summary, trainer, and weekly plan. Keep send actions confirmed, RBAC protected, CSRF protected, job-tracked, and audited. Add tests for preview and send paths.

Add safe web console workflows for weekly review and strength-test lifecycle commands, covering scripts.run_sunday_review and pete lets-begin or their application equivalents. Include typed inputs, explicit start-date confirmation where relevant, RBAC, CSRF, overlap guarding through the job service, audit/job tracking, tests for authorization/confirmation/invalid dates, and docs.

Add console forms for logging and editing nutrition macros using the existing nutrition API/application logic. Operator/owner users can add and edit logs from /console/nutrition, read-only users cannot see mutation controls, forms use CSRF and existing validation, the summary refreshes after successful changes, tests cover create/edit/authorization, and docs/web_ui_e2e_review.md is updated.

Replace the placeholder /console/admin page with a minimal real admin UI for owner-managed users and roles. Support listing users, creating users, assigning roles, and deactivating users if the backend supports it or can support it safely. Non-owner users should receive 403. Audit all changes, add tests, and update docs.

Add role-gated break-glass reference links in the console for operator/owner users. Link Operations/Admin or relevant pages to runbook sections for OAuth recovery, backup/restore, migrations, cron repair, and service restart. Do not execute shell commands from the browser for these flows. Add tests for visibility by role and update docs/web_ui_e2e_review.md.

Add web-visible operational views for alert history/active alerts and cron/scheduler status, using existing observability/alert/status data where possible. Keep the views read-only and RBAC protected. Alerts should show severity, type, timestamp, and summary with basic filtering. Scheduler status should show expected cron/scheduler configuration, highlight stale or missing scheduled runs when data is available, link to runbook repair steps, add tests, and update docs.

Add optional MFA/TOTP support for owner/operator browser users. Read the existing auth/session/RBAC code first. Implement enrollment, login challenge when enrolled, recovery codes or owner reset support, tests for enabled and disabled MFA paths, and update auth/runbook docs.

Re-review docs/web_ui_e2e_review.md and docs/web_ui_actionable_backlog.md against the current codebase after the recent changes. Update the phase completion snapshot, security posture review, workflow table, prioritized gap list, actionable backlog status, and release recommendation so the documents reflect what is now actually implemented.