# Structured Logging and Local Triage

Pete-Eebot writes one JSON object per line to `settings.log_path` (`/var/log/pete_eebot/pete_history.log` on the Pi when writable, otherwise `~/pete_logs/pete_history.log`). Set `PETE_LOG_FORMAT=json` in production. `PETE_LOG_FORMAT=text` is available only for temporary local compatibility.

## Core Schema

Every structured record includes:

| Field | Meaning |
| --- | --- |
| `schema_version` | Log schema version. Current value: `1`. |
| `timestamp` | UTC ISO-8601 timestamp. |
| `level` | Python logging level (`INFO`, `WARNING`, `ERROR`, etc.). |
| `logger` | Logger name, normally `pete_e.history`. |
| `tag` | Short source tag such as `API`, `JOB`, `AUDIT`, `SYNC`, `AUTH`. |
| `message` | Human-readable summary. |
| `event` | Machine-readable event name when emitted through structured adapters. |
| `outcome` | Result classification: `started`, `succeeded`, `failed`, `timeout`, or a domain-specific outcome. |
| `request_id` / `correlation_id` | API request correlation ID. Mirrors `X-Request-ID` and `X-Correlation-ID`. |
| `job_id` | Generated background operation ID, e.g. `sync-3f91b8a2d4c0`. |
| `auth_scheme` | `session` or `api_key` when authentication has been resolved. |
| `user_id`, `username`, `roles` | Browser user identity when session auth applies. |
| `session_id` | SHA-256 session-token fingerprint prefix. This is not the raw cookie. |

HTTP request records use:

| Field | Meaning |
| --- | --- |
| `event` | `http_request`. |
| `http_method` | Request method. |
| `http_path` | Path only, without query string. |
| `http_status` | Response status code. |
| `duration_ms` | Request duration in milliseconds. |
| `client_ip` | Caller IP, preferring `X-Forwarded-For`. |

Durable command jobs are stored in `application_jobs`; the high-risk overlap lock is stored in `application_operation_locks`. Console operators can inspect current and recent rows at `/console/jobs`. Durable command audit rows are stored in `web_console_command_history` and are searchable from `/console/history`; structured logs remain the secondary diagnostic stream. Background job log records use:

| Field | Meaning |
| --- | --- |
| `event` | `background_job`. |
| `operation` | Guarded operation name, such as `sync`, `plan`, `sunday_review`, `lets_begin`, `deploy`, or `message_resend`. |
| `job_id` | Operation correlation ID. |
| `summary.duration_ms` | Runtime for completed in-process jobs or process guards. |
| `summary.return_code` | Subprocess return code where applicable. |
| `summary.timeout_seconds` | Configured timeout for timeout outcomes. |

Subprocess jobs also persist redacted stdout/stderr summaries on the job row. Secret-like `token=`, `secret=`, `password=`, and `api_key=` fragments are redacted before storage.

Command audit records use:

| Field | Meaning |
| --- | --- |
| `web_console_command_history.request_id` | Request that initiated the command. |
| `web_console_command_history.job_id` | Job spawned by the command when available. |
| `web_console_command_history.requester_*` | Browser user identity when available. |
| `web_console_command_history.auth_scheme` | `session`, `api_key`, `github_webhook_hmac`, `cli`, or missing for pre-auth failures. |
| `web_console_command_history.command` | User-facing command name. |
| `web_console_command_history.outcome` | Command audit outcome. |
| `web_console_command_history.safe_summary` | Redacted command parameters or result summary. |
| `event` | `checkpoint`. |
| `checkpoint` | `operator_command`. |
| `outcome` | `started`, `succeeded`, `failed`, `authorization_denied`, or `confirmation_failed`. |
| `correlation.command` | User-facing command name. |
| `correlation.request_id` | Request that initiated the command. |
| `correlation.job_id` | Job spawned by the command when available. |
| `summary` | Safe command parameters or result summary. Secrets and raw tokens are redacted. |

Alert records use:

| Field | Meaning |
| --- | --- |
| `event` | `alert_event`. |
| `tag` | `ALERT`. |
| `alert_type` | `stale_ingest`, `auth_expiry`, or `repeated_failures`. |
| `severity` | `P1`, `P2`, or `P3`; see `docs/runtime_deploy_runbook.md`. |
| `title` | Short operator-facing alert title. |
| `dedupe_key` | In-process suppression key used to avoid repeated Telegram noise. |
| `summary.message` | Human-readable incident summary. |
| `summary.*` | Safe incident context such as provider, stale days, failure streak, threshold, and job ID. |

## Local Triage Workflow

1. Capture the user-visible request ID. API responses include both `X-Request-ID` and `X-Correlation-ID`; browser/API error bodies include `error.correlation_id`.
2. Find the request:

```bash
jq -c 'select(.request_id=="<request-id>")' /var/log/pete_eebot/pete_history.log
```

3. If the request started a command, note `job_id` and inspect the job:

```bash
jq -c 'select(.job_id=="<job-id>")' /var/log/pete_eebot/pete_history.log
```

Operators with browser access can also open `/console/jobs/<job-id>` to view status, timestamps, requester, exit code, failure reason, and captured output summaries.

4. Check all failed or timed-out records in the recent log:

```bash
jq -c 'select(.outcome=="failed" or .outcome=="timeout" or (.http_status // 0) >= 500)' /var/log/pete_eebot/pete_history.log
```

5. For operator commands, inspect audit events:

```bash
jq -c 'select(.tag=="AUDIT" and .checkpoint=="operator_command")' /var/log/pete_eebot/pete_history.log
```

Owner password recovery records use checkpoint `owner_password_recovery` with tag
`AUDIT`. They include the local CLI actor, target owner identity, reset outcome,
and session revocation status, but never include the submitted password or hash:

```bash
jq -c 'select(.tag=="AUDIT" and .checkpoint=="owner_password_recovery")' /var/log/pete_eebot/pete_history.log
```

Planner feature-flag audit records use checkpoint `planner_feature_flags` with tag `AUDIT`. They are emitted only when a non-default planner flag changes plan generation:

```bash
jq -c 'select(.tag=="AUDIT" and .checkpoint=="planner_feature_flags")' /var/log/pete_eebot/pete_history.log
```

6. Without shell access, use `/console/logs?lines=200` and filter by tag, outcome, `request_id`, or `job_id`. Use `GET /api/v1/logs?lines=200` when a raw machine-readable response is needed.

If `jq` is unavailable, `pete logs`, `pete logs API 100`, and `pete logs JOB 100` render both JSON and legacy text log lines.

## Metrics and Probes

The API exposes Prometheus text metrics at `GET /api/v1/metrics` and the legacy transition path `GET /metrics`. This endpoint requires the machine API key or an authenticated browser session.

```bash
curl -sS -H "X-API-Key: $PETEEEBOT_API_KEY" \
  http://127.0.0.1:8000/api/v1/metrics
```

Key emitted metrics:

| Metric | Type | Meaning |
| --- | --- | --- |
| `peteeebot_job_runs_total` | counter | Guarded job completions by `operation` and `outcome`. |
| `peteeebot_job_failures_total` | counter | Guarded job failures and timeouts. |
| `peteeebot_job_duration_seconds` | summary | Guarded job latency count/sum by operation and outcome. |
| `peteeebot_job_retries_total` | counter | Sync and external API retry attempts by operation/source. |
| `peteeebot_dependency_health` | gauge | Latest readiness result for DB and external dependencies. |
| `peteeebot_external_api_health` | gauge | Latest readiness result for Dropbox, Withings, Telegram, and wger. |
| `peteeebot_alert_events_total` | counter | Alert events by `alert_type`, `severity`, and `outcome` (`emitted` or `deduped`). |
| `peteeebot_alert_active` | gauge | Latest active alert state by `alert_type` and `severity`. |

Probe endpoints:

- `GET /healthz` is a liveness probe and does not touch dependencies.
- `GET /readyz?timeout=3` runs the same meaningful dependency checks as `/status`, including DB and external providers, but returns only coarse readiness: `{"ok":true,"status":"healthy"}` or `{"ok":false,"status":"unhealthy"}`. It returns `200` only when all checks pass and `503` when any dependency fails.
- `GET /api/v1/status?timeout=3` remains the authenticated operational status endpoint with dependency names, error details, and a human-readable summary.
