# Durable Operation Recovery

## Overview
Pete-Eebot now uses a Postgres-backed lease model for durable operations.

- Jobs enter `queued` then `running`.
- Every claim sets a process-unique `worker_id`, increments `ownership_token`,
  and establishes `last_heartbeat_at` and `lease_expires_at`.
- Callback and subprocess jobs heartbeat for their entire execution. A
  heartbeat atomically renews the job and its matching operation lock.
- Expired leases are marked `abandoned` by a periodic recovery loop, not only
  during initialization.

## Ownership and fencing
- Heartbeat, progress, completion, and failure updates require the current
  `worker_id` and `ownership_token`, an unexpired running lease, and the matching
  lock owner.
- Terminal job state and matching lock deletion commit in one transaction.
- A stale worker cannot renew, complete, fail, or release a lock after takeover.
- If heartbeat fails, ownership is considered lost. Subprocesses are terminated;
  arbitrary callbacks cannot be force-cancelled, but their late job/lock writes
  remain fenced.
- Recovery abandons expired work with `abandon_reason=lease_expired` and prunes
  only an expired or owner-mismatched lock.

## Recovery and shutdown

`ApplicationJobService` starts a periodic recovery thread when the service is
first used. A worker that starts before an old lease expires initially observes
the active lock; a later recovery pass abandons it after expiry.

Shutdown stops new admission and periodic recovery and terminates owned
subprocesses. Callback jobs drain during graceful shutdown where possible. If
the process is forcibly killed, their unrenewed leases expire and another worker
recovers them. CLI jobs close their service only after the synchronous callback
has completed.

Lease/heartbeat/recovery defaults are 300/60/60 seconds. Heartbeat must be less
than half the lease.

## Deployment ownership

The API owns only the short dispatch claim. `peteeebot-deploy@<job-id>.service`
atomically takes it over, increments the fencing token, and runs outside the API
service cgroup. A successful or failed deployment is durable even after the API
restart. A worker/host crash leaves no terminal claim; periodic recovery
abandons it after lease expiry and removes only its matching lock. Retry creates
a new job rather than replaying partially completed deployment steps.

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
