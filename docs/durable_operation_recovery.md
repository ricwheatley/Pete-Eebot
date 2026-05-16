# Durable Operation Recovery

## Overview
Pete-Eebot now uses a Postgres-backed lease model for durable operations.

- Jobs enter `queued` then `running`.
- Running jobs have `worker_id`, `last_heartbeat_at`, and `lease_expires_at`.
- A heartbeat extends lease expiry.
- Expired leases are marked `abandoned` automatically during service bootstrap recovery.

## Ownership and fencing
- A worker heartbeats with its `worker_id`.
- If heartbeat update fails, ownership is considered lost.
- Stale jobs are transitioned to `abandoned` with `abandon_reason=lease_expired`.

## Startup recovery
`ApplicationJobService` calls recovery on startup and marks stale `queued/running` jobs abandoned.

## Operations UI fields
Jobs now expose:
- `worker_id`
- `attempt_number`
- `last_heartbeat_at`
- `lease_expires_at`
- `ownership_token`
- `abandon_reason`
- `progress_summary`

## Troubleshooting
If deploys appear blocked:
1. Open `/console/jobs` and inspect active `running` job heartbeat age.
2. If `lease_expires_at` is in the past, recovery will mark it abandoned.
3. Re-trigger deploy; concurrent requests still return `409 operation_in_progress` while active lease is valid.
