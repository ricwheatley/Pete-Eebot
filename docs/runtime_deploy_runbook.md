# Runtime & Deploy Runbook (Phase 0 Source of Truth)

Last audited: 2026-05-15.

This runbook documents **what currently exists in this repository** for runtime, deploy, migrations, and ops checks.

Before exposing a host to production traffic or making a material production
change, complete `docs/production_readiness_checklist.md` and record signoff
with `docs/production_readiness_signoff_template.md`.

## Supported Deployment Profiles

Supported today:

- **Production/reference:** native Python virtual environment on an Ubuntu host, with cron/systemd orchestration and Postgres reachable from the host.
- **Local development database:** `docker compose up -d db` for Postgres only.

Not supported today:

- A containerized Pete-Eebot application image. The legacy Dockerfile was retired on 2026-05-15 because it copied paths that no longer exist (`migration.py`, `knowledge`, `integrations`) and the image was not part of the active production deploy chain.

## 1) Runtime/Deploy Topology Audit

### 1.1 CLI entrypoints

- Installed CLI command: `pete` (from `pyproject.toml` -> `pete_e.cli.messenger:app`).
- Main automation commands in active cron CSV:
  - `pete sync --days 3 --retries 3`
  - `pete morning-report --send`
  - `python3 -m scripts.run_sunday_review`
  - `pete message --plan --send`
  - `pete telegram --listen-once --limit 5 --timeout 25`
  - `python3 -m scripts.heartbeat_check`
  - `scripts/backup_db.sh`

### 1.2 Cron + systemd hooks

- Cron source of truth is `pete_e/resources/pete_crontab.csv`.
- Cron install/render path:
  - `scripts/install_cron_examples.sh`
  - `python -m pete_e.infrastructure.cron_manager --write --activate --summary`
- Service health path:
  - `scripts/heartbeat_check.py` checks `peteeebot.service` via `systemctl is-active`
  - If down, it runs `sudo -n /bin/systemctl restart peteeebot.service` and sends Telegram alert.
- Deploy path also restarts `peteeebot.service` from `pete_e/resources/deploy.sh`.

### 1.3 API service startup path

- ASGI app module: `pete_e.api:app` (FastAPI).
- Router composition happens in `pete_e/api.py`.
- Webhook deploy trigger endpoint: `POST /webhook` in `pete_e/api_routes/logs_webhooks.py`.
- Structured JSON log schema and request/job triage workflow: `docs/logging_observability.md`.
- Webhook executes configured deploy script path with `subprocess.Popen([DEPLOY_SCRIPT_PATH])` after HMAC validation.
- Production startup should bind the app to localhost behind the TLS reverse
  proxy:
  - `uvicorn pete_e.api:app --host 127.0.0.1 --port 8000`
- Do not bind production Uvicorn to `0.0.0.0` or a public interface. A
  private-network bind is allowed only for an explicitly documented private
  ingress hop where host firewall rules block direct internet access to the app
  port.

### 1.4 DB migration path

- Base schema bootstrap: `init-db/schema.sql`.
- Incremental SQL migrations are manually managed in `migrations/*.sql`.
- No Alembic or migration runner is present in repo.
- Current expected operator flow is explicit `psql` execution against schema + migration SQL files.

---

## 2) Local Development Run Steps

1. Create and activate venv.

```bash
python3 -m venv /opt/myapp/shared/venv
source /opt/myapp/shared/venv/bin/activate
```

2. Install dependencies and package.

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

3. Start local Postgres with Compose (optional local path in repo). Compose intentionally starts only Postgres; run the app from the host virtual environment.

```bash
docker compose up -d db
```

4. Initialize schema (new DB) and apply migrations (existing/new DB updates).

```bash
psql "$DATABASE_URL" -f init-db/schema.sql
for f in migrations/*.sql; do psql "$DATABASE_URL" -f "$f"; done
```

5. Sanity check integrations and service health.

```bash
python -m scripts.check_auth
pete status
```

6. Run primary local workflows.

```bash
pete sync --days 1 --retries 1
pete morning-report
pete message --summary
```

---

## 3) Production Service Run Steps (current repo-aligned model)

Assumed host layout used by deploy scripts:

- `/opt/myapp/shared/.env`
- `/opt/myapp/shared/venv`
- `/opt/myapp/current` (git checkout)

### 3.1 API service (manual start command)

```bash
cd /opt/myapp/current
set -a && . /opt/myapp/shared/.env && set +a
/opt/myapp/shared/venv/bin/uvicorn pete_e.api:app --host 127.0.0.1 --port 8000
```

The production default is loopback-only Uvicorn. Use the same host/port in the
systemd unit unless a reviewed deployment note documents a private-network-only
exception. The app port must not be reachable directly from the public internet.

### 3.2 Reverse proxy and network boundary

Production internet exposure must go through a maintained TLS reverse proxy such
as Caddy or Nginx:

- Public ingress serves HTTPS on `443`; port `80` is used only for ACME
  validation and HTTP-to-HTTPS redirect.
- The proxy forwards to `http://127.0.0.1:8000`.
- The host firewall permits public access only to intended ingress ports,
  normally `80/tcp` and `443/tcp`; `8000/tcp` remains loopback-only or blocked
  from every public interface.
- TLS certificates are automatically renewed and renewal failures are monitored.
- HTTP requests redirect to HTTPS before reaching the app.
- HSTS is enabled after HTTPS has been verified stable. Set
  `PETEEEBOT_ENABLE_HSTS=true` for app responses, or enforce an equivalent
  `Strict-Transport-Security` header at the proxy.
- The proxy forwards `Host`, scheme/proto, and client IP headers so request logs
  and redirects preserve the public request context.
- `/readyz` is unauthenticated but returns only coarse readiness. Detailed
  dependency names and errors remain behind authenticated `/api/v1/status` and
  `/console/status`.

Set conservative proxy limits. Use route-specific exceptions only when an
operator workflow really needs them:

- Request body size: default to `1m` for the API and webhook surface. Increase
  only for a documented route that accepts larger payloads.
- Request headers: cap total header size to a small operational value such as
  `8k` to `16k`.
- Header/body receive timeouts: keep short, for example `10s`.
- Upstream connect timeout: keep short, for example `5s`.
- Upstream read/send timeout: `60s` is enough for read/status/API-action calls.
  If command endpoints such as `/sync` or plan generation are intentionally
  exposed through the proxy, configure route-specific timeouts at or above the
  app command timeout (`PETEEEBOT_SYNC_TIMEOUT_SECONDS`, default `300s`, and
  `PETEEEBOT_PROCESS_TIMEOUT_SECONDS`, default `900s`) or keep those commands
  available only through trusted local/operator access.

### 3.3 Cron schedule install/refresh

```bash
cd /opt/myapp/current
set -a && . /opt/myapp/shared/.env && set +a
/opt/myapp/shared/venv/bin/python3 -m pete_e.infrastructure.cron_manager --write --activate --summary
```

### 3.4 Heartbeat service check (ad hoc)

```bash
cd /opt/myapp/current
set -a && . /opt/myapp/shared/.env && set +a
/opt/myapp/shared/venv/bin/python3 -m scripts.heartbeat_check
```

---

## 4) Deploy Flow Summary

Current deploy chain in repo:

1. Webhook hits `POST /webhook` and verifies `X-Hub-Signature-256` HMAC.
2. API process launches external deploy script at `DEPLOY_SCRIPT_PATH`.
3. Stable wrapper script (`/opt/myapp/scripts/deploy.sh`, from `pete_e/resources/deploy-wrapper.sh`) does:
   - `git fetch --all --prune`
   - `git reset --hard origin/main`
   - `git clean -fdx`
4. Wrapper executes tracked deploy script `pete_e/resources/deploy.sh` with `SKIP_GIT_UPDATE=1`.
5. Tracked deploy script does:
   - validates `.env`, venv, repo existence
   - `pip install -e <app_root>`
   - refreshes cron via `pete_e.infrastructure.cron_manager`
   - notifies Telegram
   - restarts `peteeebot.service`

---

## 5) Backup/Restore Quick Commands

### 5.1 Backup now

```bash
cd /opt/myapp/current
set -a && . /opt/myapp/shared/.env && set +a
/opt/myapp/current/scripts/backup_db.sh
```

### 5.2 Restore latest local dump

```bash
cd /opt/myapp/current
set -a && . /opt/myapp/shared/.env && set +a
export PGPASSWORD="$POSTGRES_PASSWORD"
pg_restore -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" --clean --if-exists --no-owner \
  /opt/myapp/backups/postgres/latest.dump
```

### 5.3 Decrypt cloud backup artifact before restore (if encrypted upload used)

```bash
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in postgres_latest.enc \
  -out latest.dump \
  -pass file:/path/to/backup-key
```

---

## 6) Smoke-check Commands After Deploy

Run in order. These checks deliberately exercise both the local app port and
the public HTTPS proxy path.

```bash
cd /opt/myapp/current
set -a && . /opt/myapp/shared/.env && set +a
PUBLIC_BASE_URL="https://ops.example.com"
```

```bash
/opt/myapp/shared/venv/bin/pete status
```

```bash
/bin/systemctl is-active peteeebot.service
```

```bash
/opt/myapp/shared/venv/bin/pete sync --days 1 --retries 1
```

```bash
/opt/myapp/shared/venv/bin/pete telegram --listen-once --limit 1 --timeout 10
```

```bash
curl -sS -H "X-API-Key: $PETEEEBOT_API_KEY" "http://127.0.0.1:8000/status?timeout=5"
```

```bash
curl -fsS -i "http://127.0.0.1:8000/healthz"
curl -fsS -i "http://127.0.0.1:8000/readyz?timeout=5"
```

```bash
curl -fsS -i \
  -H "X-API-Key: $PETEEEBOT_API_KEY" \
  -H "X-Correlation-ID: smoke-$(date +%Y%m%d%H%M%S)" \
  "http://127.0.0.1:8000/api/v1/status?timeout=5"
```

Confirm the response includes `X-Correlation-ID` and `X-Request-ID`. Command endpoints return the same headers on errors, including `429` rate-limit and `504` timeout responses.

Verify the public HTTPS path through the reverse proxy:

```bash
curl -fsS -D - -o /dev/null "$PUBLIC_BASE_URL/healthz"
```

```bash
curl -fsS -i \
  -H "X-API-Key: $PETEEEBOT_API_KEY" \
  -H "X-Correlation-ID: smoke-public-$(date +%Y%m%d%H%M%S)" \
  "$PUBLIC_BASE_URL/api/v1/status?timeout=5"
```

Confirm the public responses use HTTPS, include the expected security headers,
and include HSTS once production HTTPS is stable:

```bash
curl -fsS -D - -o /dev/null "$PUBLIC_BASE_URL/healthz" | grep -Ei \
  '^(strict-transport-security|content-security-policy|x-content-type-options|x-frame-options|referrer-policy|permissions-policy):'
```

Include the public coarse readiness probe in the HTTPS smoke transcript:

```bash
curl -fsS -D - -o /dev/null "$PUBLIC_BASE_URL/readyz?timeout=5"
```

Confirm direct public access to the app port fails from a network outside the
host:

```bash
curl --connect-timeout 5 -sS -i "http://<public-host-or-ip>:8000/healthz"
```

This last command should fail to connect or time out. A successful response
means Uvicorn or the firewall/proxy boundary is exposed incorrectly.

Prometheus-compatible metrics are exposed on the versioned metrics endpoint:

```bash
curl -fsS -H "X-API-Key: $PETEEEBOT_API_KEY" \
  "http://127.0.0.1:8000/api/v1/metrics"
```

The scrape includes guarded job latency/counts, job failures, retry counters, and latest dependency health gauges. Prometheus scrape jobs should send the machine key as `X-API-Key` and target `/api/v1/metrics`.

Durable command execution uses `application_jobs` for status/history and `application_operation_locks` for the shared high-risk lock. Command audit events are also persisted to `web_console_command_history`, linking request ID, job ID, user, auth scheme, command, outcome, client identity, and a redacted safe summary. Inspect `/console/jobs` for execution state and `/console/history` or `/console/history.json?q=<request-or-job-id>` for searchable recent command audit history. Structured `AUDIT` and `JOB` log lines remain a secondary diagnostic stream for correlation and raw incident timelines.

Daily operators can use `/console/operations` to preview the morning report
without sending it or send it via Telegram after typing `SEND MORNING REPORT`.
Both paths accept the same optional date override as `pete morning-report --date`;
failed attempts surface request/job IDs for lookup in Jobs, History, and Logs.

---

## 7) Security Operations

### 7.1 Browser session hardening

Browser users authenticate with `/auth/login`, receive an HTTP-only session cookie, and must send the readable CSRF cookie value back in `X-CSRF-Token` for state-changing requests. Session cookies should stay secure in production:

```bash
PETEEEBOT_SESSION_COOKIE_SECURE=true
PETEEEBOT_SESSION_COOKIE_SAMESITE=lax
PETEEEBOT_SESSION_COOKIE_DOMAIN=
```

Failed login attempts are tracked per normalized login and client address inside the API process. Defaults:

```bash
PETEEEBOT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS=5
PETEEEBOT_LOGIN_RATE_LIMIT_WINDOW_SECONDS=300
PETEEEBOT_LOGIN_LOCKOUT_SECONDS=900
PETEEEBOT_LOGIN_BACKOFF_BASE_SECONDS=1
```

The first failures return normal authentication errors, immediate retries are backed off with `429`, and repeated failures lock the login/client tuple temporarily with `Retry-After`.

### 7.2 First owner bootstrap and local recovery

Browser owner accounts are created from the host shell only. There is no public
HTTP route for first-owner bootstrap.

Before starting the web console for the first time, apply the auth migration and
create one owner:

```bash
psql "$DATABASE_URL" -f migrations/20260515_add_auth_users_sessions_rbac.sql
psql "$DATABASE_URL" -f migrations/20260516_add_auth_mfa_fields.sql
pete bootstrap-owner --username ric --email ric@example.com --display-name "Ric"
```

The command prompts for the password with hidden input and confirmation. For
non-interactive provisioning, pass the password through an environment variable
instead of putting it on the command line:

```bash
PETEEEBOT_BOOTSTRAP_OWNER_PASSWORD="$(pass show peteeebot/browser-owner)" \
  pete bootstrap-owner --username ric --email ric@example.com --display-name "Ric"
```

`pete bootstrap-owner` always creates the account with the `owner` role, hashes
the password through the application password helper, rejects duplicate
usernames/emails, and refuses to run once an active owner already exists.

Lost owner password recovery is also shell-only:

```bash
PETEEEBOT_RESET_OWNER_PASSWORD="$(pass show peteeebot/browser-owner-new)" \
  pete reset-owner-password --login ric@example.com
```

That command only targets existing active owners, updates the password hash, and
revokes that owner's browser sessions. It emits an `AUDIT` checkpoint named
`owner_password_recovery` with the local CLI actor, target owner identity, reset
outcome, and whether sessions were revoked. It never logs the submitted password
or the resulting password hash.

Verify the reset audit record before handing the account back:

```bash
jq -c 'select(.tag=="AUDIT" and .checkpoint=="owner_password_recovery")' \
  /var/log/pete_eebot/pete_history.log
```

If the account is temporarily locked by failed login throttling, either wait
`PETEEEBOT_LOGIN_LOCKOUT_SECONDS` or restart the API process to clear the
in-memory throttle state after verifying the reset.

Owners can manage routine browser users from `/console/admin` after signing in.
The page lists users, creates users, assigns roles, deactivates users, and resets
MFA for locked-out owner/operator users. These actions require an active owner
session, a CSRF token, and write an `AUDIT` operator-command event.

Owner/operator users can enroll optional MFA from `/console/security`. The flow
returns a TOTP secret, an authenticator URI, and one-time recovery codes. After a
valid 6-digit TOTP confirmation, future logins require either a current TOTP
code or one unused recovery code. Store recovery codes in the same password
manager as the browser account password. If recovery codes are lost, an owner
can reset MFA for the affected user from `/console/admin`.

### 7.3 CORS and security headers

CORS is fail-closed by default. Leave `PETEEEBOT_CORS_ALLOWED_ORIGINS` empty for same-origin browser deployment. If the UI is served from a separate origin, set an explicit comma-separated allowlist:

```bash
PETEEEBOT_CORS_ALLOWED_ORIGINS=https://ops.example.com
PETEEEBOT_ENABLE_HSTS=true
```

The API applies baseline response headers: `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and production HSTS.

### 7.4 Machine API-key scope

`PETEEEBOT_API_KEY` is for machine actors only, such as private GPT actions, internal automation, and smoke checks. It is accepted only on the explicit machine API route set documented in `docs/api_endpoint_inventory.md`; browser auth endpoints such as `/auth/login`, `/auth/logout`, and `/auth/session` do not accept it.

Browser users should use session cookies and RBAC. Read-only users can read summaries/plans/logs; command endpoints such as `/sync`, `/run_pete_plan_async`, and nutrition writes require an `operator` or `owner` session. Machine API-key calls remain available for the listed machine endpoints and are not treated as browser users.

### 7.5 Machine API-key rotation

Use this procedure whenever the key may have leaked, after changing GPT/action clients, and on a regular maintenance cadence.

1. Generate a new high-entropy key on the host:

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

2. Update `PETEEEBOT_API_KEY` in `/opt/myapp/shared/.env`. Do not commit the value.
3. Update every machine client that sends `X-API-Key`, including private GPT action configuration, Postman/local smoke-check environments, and trusted automation.
4. Restart the API service so the new environment is loaded:

```bash
sudo systemctl restart peteeebot.service
```

5. Verify the new key and confirm the old key fails:

```bash
curl -i -H "X-API-Key: $PETEEEBOT_API_KEY" "http://127.0.0.1:8000/api/v1/status?timeout=5"
curl -i -H "X-API-Key: <old-key>" "http://127.0.0.1:8000/api/v1/status?timeout=5"
```

The first call should return `200`; the old key should return `401`.

### 7.6 Planner feature flags

Planner experiments default off. Configure them only through explicit environment overrides:

```bash
PETEEEBOT_PLANNER_FEATURE_FLAGS=""
PETEEEBOT_PLANNER_FEATURE_FLAGS="experimental_relaxed_session_spacing=true"
```

Restart the API/job process after changing the value. See `docs/planner_feature_flags.md` for the current flag registry, audit-log query, and rollback procedure.

### 7.7 Optional multi-profile foundation

The coached-person profile layer is optional. Existing single-user deployments
continue to use the `USER_DATE_OF_BIRTH`, `USER_HEIGHT_CM`,
`USER_GOAL_WEIGHT_KG`, and `USER_TIMEZONE` settings as the default profile
facts. Apply the Phase 5.3 schema only when you want database-backed profile
metadata:

```bash
psql "$DATABASE_URL" -f migrations/20260515_add_user_profiles.sql
```

The migration does not rewrite or split existing training, nutrition, Withings,
Apple, or wger data. See `docs/multi_profile_migration_note.md` for apply,
rollback, and future profile-scoping guidance.

---

## 8) Stale Commands / Drift Found During Phase 0 Audit

### 8.1 Retired container app image

- Removed the legacy app `Dockerfile`.
- Removed the Compose `app` service that built the stale image and then idled with `tail -f /dev/null`.
- Kept `docker-compose.yml` as the supported local Postgres helper.
- If a containerized app profile is needed later, create a fresh Dockerfile around the packaged project (`pyproject.toml`, `requirements.txt`, `pete_e/`, `scripts/`, `init-db/`, and `migrations/`) and define a real API/worker command instead of restoring the old migration-image assumptions.

### 8.2 Disabled/missing cron scripts

The following entries exist in cron CSV but referenced scripts are missing in this repo snapshot:

- `python3 -m scripts.log_rotate` (**missing `scripts/log_rotate.py`**)
- `python3 -m scripts.check_for_updates` (**missing `scripts/check_for_updates.py`**)
- `python3 -m scripts.full_backup` (**missing `scripts/full_backup.py`**)
- `python3 -m scripts.cleanup_old_backups` (**missing `scripts/cleanup_old_backups.py`**)

Current replacement guidance:

- Use `scripts/backup_db.sh` for operational backups (already present and wired).
- Keep the corresponding cron rows disabled until replacement scripts are added.

---

## 9) Alert Response Playbooks

Pete-Eebot emits alert events through structured logs, Prometheus metrics, and Telegram when `PETEEEBOT_ALERT_TELEGRAM_ENABLED=true`.

Runtime alert controls:

```bash
PETEEEBOT_ALERT_TELEGRAM_ENABLED=true
PETEEEBOT_ALERT_DEDUPE_SECONDS=3600
PETEEEBOT_STALE_INGEST_ALERT_DAYS=3
PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD=3
```

Alert metrics:

- `peteeebot_alert_events_total{alert_type,severity,outcome}` counts emitted and deduped alerts.
- `peteeebot_alert_active{alert_type,severity}` marks the latest in-process active alert state.

Structured alert logs use `tag=ALERT`, `event=alert_event`, `alert_type`, `severity`, `dedupe_key`, and a safe `summary` object. See `docs/logging_observability.md` for the full schema.

### 9.1 Severity mapping and response expectations

| Severity | Meaning | Response expectation |
| --- | --- | --- |
| `P1` | Automation cannot be trusted or an auth token is unrecoverable without action. Examples: no ingest baseline at all, ingest stale for 7+ days, repeated failures continuing well past threshold, invalid refresh token. | Acknowledge immediately during waking hours. Stop relying on generated coaching output until status is green or the incident is understood. Rotate/reauth/fix before the next scheduled report. |
| `P2` | Core workflow degraded but diagnosis can start from the console. Examples: ingest stale for 3-6 days, Withings/Dropbox/wger auth check reports token expiry, sync/plan/message command failure streak reaches threshold. | Investigate same day. Use console Status, Logs, and Operations pages to isolate source and run one confirmed remediation command if appropriate. |
| `P3` | Warning-level degradation or early signal. Examples: lower freshness threshold in a test profile, transient alert before repeated-failure threshold escalates. | Review during next operating window. Watch for repeat alerts or worsening readiness/source quality. |

### 9.2 No-shell incident diagnosis

Use these steps when you only have browser/API access:

1. Open `/console/status`.
2. Check **Health Checks** for failed dependencies. A provider detail containing `expired`, `unauthorized`, `invalid_grant`, or `invalid refresh` maps to an auth-expiry incident.
3. Check **Sync Freshness** for `Last data date`, `Stale days`, `Reliability`, and `Completeness`.
4. Check **Last Sync Outcome** for source-level failures. The failed source narrows the next action.
5. Open `/console/history` and search by request ID, job ID, command, user, or outcome to confirm which operator command ran and whether it was accepted, rejected, queued, or failed.
6. Open `/console/logs?lines=200`. Filter for `ALERT`, `ERROR`, `failed`, the alert `dedupe_key`, or a visible request/job ID. Use `GET /api/v1/logs?lines=200` only when a raw API response is easier.
7. If the fault is stale ingest or a transient source failure, use `/console/operations` to run a confirmed sync once.
8. Re-open `/console/status` and confirm readiness, freshness, and last sync source statuses.
9. If the alert remains P1/P2 after one confirmed remediation attempt, avoid repeated manual commands and move to shell/operator access or provider reauthorization.

### 9.3 Stale ingest playbook

Trigger: `alert_type=stale_ingest`.

Primary diagnosis without shell:

- `/console/status` -> **Sync Freshness** shows stale days and completeness.
- `/console/status` -> **Last Sync Outcome** shows whether the previous run failed by source.
- `/console/history?command=sync` shows the latest accepted/rejected manual sync commands with request/job correlation.
- `/console/logs?lines=200` shows the last `Sync summary` and any `ALERT` event.

Response:

- If `Last Sync Outcome` is missing, check whether cron/service health is also failing in **Health Checks**.
- If one source failed, treat it as a provider-specific incident first.
- If all sources are old, run one manual sync from `/console/operations`.
- For `P1`, pause trust in daily coaching output until the console shows fresh data.

### 9.4 Auth expiry playbook

Trigger: `alert_type=auth_expiry`.

Primary diagnosis without shell:

- `/console/status` -> failed provider detail usually names `token expired`, `unauthorized`, `invalid_grant`, or missing credentials.
- `GET /api/v1/status?timeout=5` gives the same provider check details for machine clients.
- `/console/logs?lines=200` shows the alert and the dependency check failure.

Response:

- Withings: complete the Withings browser auth flow documented in `docs/operator_guide.md`, then verify with `/console/status`.
- Dropbox: refresh the Dropbox app credentials/refresh token in the environment, then restart through normal deploy/service operations.
- wger: verify `WGER_API_KEY` or username/password auth settings.
- Do not repeatedly run sync while auth remains expired; it will only extend the failure streak.

### 9.5 Repeated failure playbook

Trigger: `alert_type=repeated_failures`.

Primary diagnosis without shell:

- `/console/history` -> filter by the alert `job_id`, request ID, command, or `outcome=failed`.
- `/console/logs?lines=200` -> filter by the alert `job_id` or operation name.
- `/console/status` -> compare health checks and last sync source failures.
- `/console/operations` -> confirm whether a command is currently rate-limited or blocked by the high-risk operation guard.

Response:

- If the failures are sync failures with a single failed source, follow the provider-specific stale/auth playbook.
- If failures are timeouts, check whether the operation eventually completed in logs before retrying.
- If repeated failures are from plan or message resend commands, do not retry more than once from the console; escalate to shell access so process output and environment can be inspected.

