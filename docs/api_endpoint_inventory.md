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
| GET | `/coach_state?date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Coach context/readiness state. |
| GET | `/goal_state` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Current goal metadata. |
| GET | `/user_notes?days=N` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Recent user notes. |
| GET | `/plan_context?date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Active plan phase/context. |
| GET | `/sse` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/metrics.py` | Server-sent heartbeat stream. |
| GET | `/nutrition/daily-summary?date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/nutrition.py` | Nutrition aggregate for a day. |
| POST | `/nutrition/log-macros` | Command | Machine `X-API-Key` or `operator`/`owner` browser session | `pete_e/api_routes/nutrition.py` | Creates a nutrition log entry. |
| PATCH | `/nutrition/log-macros/{log_id}` | Command | Machine `X-API-Key` or `operator`/`owner` browser session | `pete_e/api_routes/nutrition.py` | Updates a nutrition log entry. |
| GET | `/plan_for_day?date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/plan.py` | Planned workout rows for one day. |
| GET | `/plan_for_week?start_date=YYYY-MM-DD` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/plan.py` | Planned workout rows for one week. |
| GET | `/plan_decision_trace?plan_id=N&week_number=N` | Read | Machine `X-API-Key` or browser session | `pete_e/api_routes/plan.py` | Planner decision trace for one plan week. |
| POST | `/run_pete_plan_async?weeks=N&start_date=YYYY-MM-DD` | Command | Machine `X-API-Key` or `operator`/`owner` browser session | `pete_e/api_routes/plan.py` | Starts `pete plan`; guarded as high-risk until the spawned process exits. |
| GET | `/status?timeout=N` | Admin | Machine `X-API-Key` or browser session | `pete_e/api_routes/status_sync.py` | Runs operational health checks. |
| POST | `/sync?days=N&retries=N` | Command | Machine `X-API-Key` or `operator`/`owner` browser session | `pete_e/api_routes/status_sync.py` | Runs sync in-process; guarded as high-risk for the duration of the call. |
| GET | `/logs?lines=N` | Admin | Machine `X-API-Key` or browser session | `pete_e/api_routes/logs_webhooks.py` | Returns recent application log lines. |
| POST | `/webhook` | Admin | GitHub HMAC | `pete_e/api_routes/logs_webhooks.py` | Deploy-sensitive GitHub webhook; guarded as high-risk until the deploy process exits. |

Protected machine routes reject `api_key` query parameters. Send the machine key only in the `X-API-Key` header so secrets do not leak into browser history, logs, or referrers. Browser-only auth/session routes do not accept the machine API key.

Browser sessions are role checked. Read routes allow any authenticated user. Command routes require an `operator` or `owner` session and valid CSRF token for browser requests.

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

The current Phase 0 guard is process-local and intentionally minimal. It serializes API-triggered high-risk workflows so only one of these can run at a time in the API process:

- `POST /sync`
- `POST /run_pete_plan_async`
- `POST /webhook`

Overlap attempts return `409 Conflict` with the requested and currently active operation names in the shared error envelope. The guard covers the full synchronous sync call, and it remains held for plan/deploy subprocesses until their `wait()` completes.

## Command Protections

State-changing command routes have process-local throttling. Defaults are:

- `PETEEEBOT_COMMAND_RATE_LIMIT_MAX_REQUESTS=10`
- `PETEEEBOT_COMMAND_RATE_LIMIT_WINDOW_SECONDS=60`

When exceeded, the API returns `429` with `error.code=rate_limited` and a `Retry-After` header.

High-risk commands also have execution time bounds:

- `POST /sync`: default `timeout=300` seconds, accepted query range `1..900`.
- `POST /run_pete_plan_async`: default subprocess timeout `900` seconds, accepted query range `30..3600`.
- `POST /webhook`: uses `PETEEEBOT_PROCESS_TIMEOUT_SECONDS` for the deploy subprocess.

If synchronous command execution exceeds its timeout, the API returns `504` with `error.code=command_timeout`. The underlying guarded operation remains protected until its worker actually finishes, so a timed-out sync cannot immediately overlap with plan or deploy.
