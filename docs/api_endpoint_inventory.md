# API Endpoint Inventory

Last audited: 2026-05-15.

Versioning note: each path below is also mounted under `/api/v1` as the preferred API surface. For example, `/metrics_overview` is available as `/api/v1/metrics_overview`. Unversioned routes remain temporarily for backward compatibility and are deprecated from 2026-05-15; see `docs/api_v1_migration_note.md`.

Classification definitions:

- **Read:** returns data or status without mutating application state.
- **Command:** mutates user/application state or starts an operator workflow.
- **Admin:** operational or deploy surface that should remain restricted to trusted operators/automation.

| Method | Path | Classification | Auth | Source | Notes |
| --- | --- | --- | --- | --- | --- |
| GET | `/` | Read | None | `pete_e/api_routes/root.py` | Root health/banner response. |
| POST | `/` | Read | None | `pete_e/api_routes/root.py` | Backward-compatible no-op root response; does not mutate state. |
| GET | `/metrics_overview?date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Metrics dashboard overview for a date. |
| GET | `/daily_summary?date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Daily health/training summary. |
| GET | `/recent_workouts?days=N&end_date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Recent workout history. |
| GET | `/coach_state?date=YYYY-MM-DD&profile=slug` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Coach context/readiness state; `profile` is optional and defaults to the single-user profile. |
| GET | `/goal_state?profile=slug` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Current goal metadata; `profile` is optional and defaults to the single-user profile. |
| GET | `/user_notes?days=N` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Recent user notes. |
| GET | `/plan_context?date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Active plan phase/context. |
| GET | `/sse` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Server-sent heartbeat stream. |
| GET | `/nutrition/daily-summary?date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/nutrition.py` | Nutrition aggregate for a day. |
| POST | `/nutrition/log-macros` | Command | Machine `X-API-Key` or `operator`/`owner` browser session | `pete_e/api_routes/nutrition.py` | Creates a nutrition log entry. |
| PATCH | `/nutrition/log-macros/{log_id}` | Command | Machine `X-API-Key` or `operator`/`owner` browser session | `pete_e/api_routes/nutrition.py` | Updates a nutrition log entry. |
| GET | `/plan_for_day?date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/plan.py` | Planned workout rows for one day. |
| GET | `/plan_for_week?start_date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/plan.py` | Planned workout rows for one week. |
| GET | `/plan_decision_trace?plan_id=N&week_number=N` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/plan.py` | Planner decision trace for one plan week. |
| POST | `/run_pete_plan_async?weeks=N&start_date=YYYY-MM-DD` | Command | Machine `X-API-Key` or `operator`/`owner` browser session | `pete_e/api_routes/plan.py` | Queues a durable `plan` job that starts `pete plan`; guarded as high-risk until the spawned process exits. |
| GET | `/healthz` | Read | None | `pete_e/api_routes/status_sync.py` | Liveness probe; confirms the API process can serve requests without running dependency checks. |
| GET | `/readyz?timeout=N` | Read | None | `pete_e/api_routes/status_sync.py` | Public readiness probe; runs DB and external dependency checks, returns only coarse `healthy`/`unhealthy` status, and returns `503` when any check fails. |
| GET | `/metrics` | Admin | Machine `X-API-Key` or browser session | `pete_e/api_routes/status_sync.py` | Prometheus text metrics for guarded jobs, retries, failures, and dependency health. |
| GET | `/status?timeout=N` | Admin | Machine `X-API-Key` or browser session | `pete_e/api_routes/status_sync.py` | Runs operational health checks. |
| POST | `/sync?days=N&retries=N` | Command | Machine `X-API-Key` or `operator`/`owner` browser session | `pete_e/api_routes/status_sync.py` | Runs sync as a durable `sync` job; guarded as high-risk until the sync worker finishes. |
| GET | `/logs?lines=N` | Admin | Machine `X-API-Key` or browser session | `pete_e/api_routes/logs_webhooks.py` | Returns recent application log lines. |
| POST | `/webhook` | Admin | GitHub HMAC | `pete_e/api_routes/logs_webhooks.py` | Queues a durable `deploy` job for the deploy script; guarded as high-risk until the deploy process exits. |

Protected machine routes reject `api_key` query parameters. Send the machine key only in the `X-API-Key` header so secrets do not leak into browser history, logs, or referrers. Browser-only auth/session routes do not accept the machine API key.

Browser sessions are role checked. Read routes allow any authenticated user. Command routes require an `operator` or `owner` session and valid CSRF token for browser requests.

## Browser Console Command Routes

The server-rendered operator console is mounted outside `/api/v1`. These routes are browser-session only and do not accept the machine API key.

| Method | Path | Classification | Auth | Source | Notes |
| --- | --- | --- | --- | --- | --- |
| GET | `/console/logs?lines=N&tag=TAG&outcome=OUTCOME` | Read | Any authenticated browser session | `pete_e/api_routes/web.py` | Renders recent application logs with request/job columns and basic filters. |
| GET | `/console/jobs` | Read | `operator`/`owner` browser session | `pete_e/api_routes/web.py` | Renders current and recent durable command jobs. |
| GET | `/console/jobs/{job_id}` | Read | `operator`/`owner` browser session | `pete_e/api_routes/web.py` | Renders one job with captured stdout/stderr summaries when present. |
| GET | `/console/jobs/{job_id}/status` | Read | `operator`/`owner` browser session | `pete_e/api_routes/web.py` | Returns one job status as JSON for polling. |
| GET | `/console/history?q=TEXT&command=NAME&outcome=OUTCOME&limit=N` | Read | `operator`/`owner` browser session | `pete_e/api_routes/web.py` | Renders searchable durable command audit history with request/job/user/auth correlation. |
| GET | `/console/history.json?q=TEXT&command=NAME&outcome=OUTCOME&limit=N` | Read | `operator`/`owner` browser session | `pete_e/api_routes/web.py` | Returns recent command audit history as JSON for console polling or diagnostics. |
| GET | `/console/operations` | Read | `operator`/`owner` browser session | `pete_e/api_routes/web.py` | Renders command controls with typed confirmation phrases. |
| POST | `/console/operations/run-sync` | Command | `operator`/`owner` browser session + CSRF + typed confirmation | `pete_e/api_routes/web.py` | Creates a durable `sync` job through the high-risk operation guard. Confirmation phrase: `RUN SYNC`. |
| POST | `/console/operations/generate-plan` | Command | `operator`/`owner` browser session + CSRF + typed confirmation | `pete_e/api_routes/web.py` | Creates a durable `plan` job that starts `pete plan`. Confirmation phrase: `GENERATE PLAN`. |
| POST | `/console/operations/run-sunday-review` | Command | `operator`/`owner` browser session + CSRF + typed confirmation | `pete_e/api_routes/web.py` | Creates a durable `sunday_review` job that starts `python -m scripts.run_sunday_review`. Confirmation phrase: `RUN SUNDAY REVIEW`. |
| POST | `/console/operations/lets-begin` | Command | `operator`/`owner` browser session + CSRF + typed confirmation + start-date confirmation | `pete_e/api_routes/web.py` | Creates a durable `lets_begin` job that starts `pete lets-begin --start-date YYYY-MM-DD`. Requires the `start_date` field and an exact matching `start_date_confirmation`. Confirmation phrase: `BEGIN STRENGTH TEST`. |
| POST | `/console/operations/resend-message` | Command | `operator`/`owner` browser session + CSRF + typed confirmation | `pete_e/api_routes/web.py` | Creates a durable `message_resend` job that starts `pete message --<type> --send`. Confirmation phrase: `RESEND MESSAGE`. |

## Error and Correlation Contract

All API errors use a common envelope:

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Invalid or missing API key",
    "correlation_id": "7f0f4a10-2e67-4b5a-94a9-9e8f27dbcf5d"
  }
}
```

When useful, `error.details` contains machine-readable context such as the active guarded operation or validation errors.

Clients may send either `X-Correlation-ID` or `X-Request-ID`. If neither is present, the API generates a UUID. Responses include both `X-Correlation-ID` and `X-Request-ID` with the resolved value so UI clients and logs can tie a failed request to operator-visible diagnostics.

## High-Risk Operation Guard

High-risk workflows are serialized with the database-backed `application_operation_locks` table. This protects API, console, cron, and multi-worker API deployments from overlapping the shared command surface:

- `POST /sync`
- `POST /run_pete_plan_async`
- `POST /webhook`
- `/console/operations/run-sync`
- `/console/operations/generate-plan`
- `/console/operations/run-sunday-review`
- `/console/operations/lets-begin`
- `/console/operations/resend-message`
- `pete sync`

Overlap attempts return `409 Conflict` with the requested and currently active operation names in the shared error envelope. The durable lock is held for the full sync worker, and it remains held for plan, message resend, and deploy subprocesses until the spawned process exits or times out. Jobs are persisted in `application_jobs`; command responses include `job_id` and, where applicable, a `/console/jobs/<job_id>` URL.

## Command Protections

State-changing command routes have process-local throttling. Defaults are:

- `PETEEEBOT_COMMAND_RATE_LIMIT_MAX_REQUESTS=10`
- `PETEEEBOT_COMMAND_RATE_LIMIT_WINDOW_SECONDS=60`

When exceeded, the API returns `429` with `error.code=rate_limited` and a `Retry-After` header.

High-risk commands also have execution time bounds:

- `POST /sync`: default `timeout=300` seconds, accepted query range `1..900`.
- `POST /run_pete_plan_async`: default subprocess timeout `900` seconds, accepted query range `30..3600`.
- `POST /webhook`: uses `PETEEEBOT_PROCESS_TIMEOUT_SECONDS` for the deploy subprocess.

If synchronous command execution exceeds its timeout, the API returns `504` with `error.code=command_timeout` and the durable `job_id`. The underlying guarded operation remains protected until its worker actually finishes, so a timed-out sync cannot immediately overlap with plan, message resend, or deploy.

## Command Audit Logging

Operator command handlers persist the same audit fields to `web_console_command_history` and also emit `CHECKPOINT` log entries with tag `AUDIT` and checkpoint `operator_command`. Events include the command name, outcome, correlation ID, authenticated user where available, auth scheme, client identity, and a redacted summary. Browser console handlers audit `authorization_denied`, `confirmation_failed`, `started`, `succeeded`, and `failed` outcomes. Existing API-triggered sync, plan, and deploy commands also audit start/success/failure outcomes.
