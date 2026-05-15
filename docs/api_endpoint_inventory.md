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
| GET | `/metrics_overview?date=YYYY-MM-DD` | Read | API key | `pete_e/api_routes/metrics.py` | Metrics dashboard overview for a date. |
| GET | `/daily_summary?date=YYYY-MM-DD` | Read | API key | `pete_e/api_routes/metrics.py` | Daily health/training summary. |
| GET | `/recent_workouts?days=N&end_date=YYYY-MM-DD` | Read | API key | `pete_e/api_routes/metrics.py` | Recent workout history. |
| GET | `/coach_state?date=YYYY-MM-DD` | Read | API key | `pete_e/api_routes/metrics.py` | Coach context/readiness state. |
| GET | `/goal_state` | Read | API key | `pete_e/api_routes/metrics.py` | Current goal metadata. |
| GET | `/user_notes?days=N` | Read | API key | `pete_e/api_routes/metrics.py` | Recent user notes. |
| GET | `/plan_context?date=YYYY-MM-DD` | Read | API key | `pete_e/api_routes/metrics.py` | Active plan phase/context. |
| GET | `/sse` | Read | API key | `pete_e/api_routes/metrics.py` | Server-sent heartbeat stream. |
| GET | `/nutrition/daily-summary?date=YYYY-MM-DD` | Read | API key | `pete_e/api_routes/nutrition.py` | Nutrition aggregate for a day. |
| POST | `/nutrition/log-macros` | Command | API key | `pete_e/api_routes/nutrition.py` | Creates a nutrition log entry. |
| PATCH | `/nutrition/log-macros/{log_id}` | Command | API key | `pete_e/api_routes/nutrition.py` | Updates a nutrition log entry. |
| GET | `/plan_for_day?date=YYYY-MM-DD` | Read | API key | `pete_e/api_routes/plan.py` | Planned workout rows for one day. |
| GET | `/plan_for_week?start_date=YYYY-MM-DD` | Read | API key | `pete_e/api_routes/plan.py` | Planned workout rows for one week. |
| GET | `/plan_decision_trace?plan_id=N&week_number=N` | Read | API key | `pete_e/api_routes/plan.py` | Planner decision trace for one plan week. |
| POST | `/run_pete_plan_async?weeks=N&start_date=YYYY-MM-DD` | Command | API key | `pete_e/api_routes/plan.py` | Starts `pete plan`; guarded as high-risk until the spawned process exits. |
| GET | `/status?timeout=N` | Admin | API key | `pete_e/api_routes/status_sync.py` | Runs operational health checks. |
| POST | `/sync?days=N&retries=N` | Command | API key | `pete_e/api_routes/status_sync.py` | Runs sync in-process; guarded as high-risk for the duration of the call. |
| GET | `/logs?lines=N` | Admin | API key | `pete_e/api_routes/logs_webhooks.py` | Returns recent application log lines. |
| POST | `/webhook` | Admin | GitHub HMAC | `pete_e/api_routes/logs_webhooks.py` | Deploy-sensitive GitHub webhook; guarded as high-risk until the deploy process exits. |

## High-Risk Operation Guard

The current Phase 0 guard is process-local and intentionally minimal. It serializes API-triggered high-risk workflows so only one of these can run at a time in the API process:

- `POST /sync`
- `POST /run_pete_plan_async`
- `POST /webhook`

Overlap attempts return `409 Conflict` with the requested and currently active operation names. The guard covers the full synchronous sync call, and it remains held for plan/deploy subprocesses until their `wait()` completes.
