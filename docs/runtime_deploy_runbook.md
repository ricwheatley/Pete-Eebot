# Runtime & Deploy Runbook (Phase 0 Source of Truth)

Last audited: 2026-05-15.

This runbook documents **what currently exists in this repository** for runtime, deploy, migrations, and ops checks.

## Supported Deployment Profiles

Supported today:

- **Production/reference:** native Python virtual environment on a Linux/Raspberry Pi host, with cron/systemd orchestration and Postgres reachable from the host.
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
- Operator guide startup command currently documented as:
  - `uvicorn pete_e.api:app --host 0.0.0.0 --port 8000`

### 1.4 DB migration path

- Base schema bootstrap: `init-db/schema.sql`.
- Incremental SQL migrations are manually managed in `migrations/*.sql`.
- No Alembic or migration runner is present in repo.
- Current expected operator flow is explicit `psql` execution against schema + migration SQL files.

---

## 2) Local Development Run Steps

1. Create and activate venv.

```bash
python3 -m venv .venv
source .venv/bin/activate
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

- `/home/ricwheatley/pete-eebot/.env`
- `/home/ricwheatley/pete-eebot/venv`
- `/home/ricwheatley/pete-eebot/app` (git checkout)

### 3.1 API service (manual start command)

```bash
cd /home/ricwheatley/pete-eebot/app
set -a && . /home/ricwheatley/pete-eebot/.env && set +a
/home/ricwheatley/pete-eebot/venv/bin/uvicorn pete_e.api:app --host 0.0.0.0 --port 8000
```

### 3.2 Cron schedule install/refresh

```bash
cd /home/ricwheatley/pete-eebot/app
set -a && . /home/ricwheatley/pete-eebot/.env && set +a
/home/ricwheatley/pete-eebot/venv/bin/python3 -m pete_e.infrastructure.cron_manager --write --activate --summary
```

### 3.3 Heartbeat service check (ad hoc)

```bash
cd /home/ricwheatley/pete-eebot/app
set -a && . /home/ricwheatley/pete-eebot/.env && set +a
/home/ricwheatley/pete-eebot/venv/bin/python3 -m scripts.heartbeat_check
```

---

## 4) Deploy Flow Summary

Current deploy chain in repo:

1. Webhook hits `POST /webhook` and verifies `X-Hub-Signature-256` HMAC.
2. API process launches external deploy script at `DEPLOY_SCRIPT_PATH`.
3. Stable wrapper script (`/home/ricwheatley/pete-eebot/deploy.sh`, from `pete_e/resources/deploy-wrapper.sh`) does:
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
cd /home/ricwheatley/pete-eebot/app
set -a && . /home/ricwheatley/pete-eebot/.env && set +a
/home/ricwheatley/pete-eebot/app/scripts/backup_db.sh
```

### 5.2 Restore latest local dump

```bash
cd /home/ricwheatley/pete-eebot/app
set -a && . /home/ricwheatley/pete-eebot/.env && set +a
export PGPASSWORD="$POSTGRES_PASSWORD"
pg_restore -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" --clean --if-exists --no-owner \
  /home/ricwheatley/pete-eebot/backups/postgres/latest.dump
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

Run in order:

```bash
cd /home/ricwheatley/pete-eebot/app
set -a && . /home/ricwheatley/pete-eebot/.env && set +a
```

```bash
/home/ricwheatley/pete-eebot/venv/bin/pete status
```

```bash
/bin/systemctl is-active peteeebot.service
```

```bash
/home/ricwheatley/pete-eebot/venv/bin/pete sync --days 1 --retries 1
```

```bash
/home/ricwheatley/pete-eebot/venv/bin/pete telegram --listen-once --limit 1 --timeout 10
```

```bash
curl -sS -H "X-API-Key: $PETEEEBOT_API_KEY" "http://127.0.0.1:8000/status?timeout=5"
```

```bash
curl -sS -i \
  -H "X-API-Key: $PETEEEBOT_API_KEY" \
  -H "X-Correlation-ID: smoke-$(date +%Y%m%d%H%M%S)" \
  "http://127.0.0.1:8000/api/v1/status?timeout=5"
```

Confirm the response includes `X-Correlation-ID` and `X-Request-ID`. Command endpoints return the same headers on errors, including `429` rate-limit and `504` timeout responses.

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

### 7.2 CORS and security headers

CORS is fail-closed by default. Leave `PETEEEBOT_CORS_ALLOWED_ORIGINS` empty for same-origin browser deployment. If the UI is served from a separate origin, set an explicit comma-separated allowlist:

```bash
PETEEEBOT_CORS_ALLOWED_ORIGINS=https://ops.example.com
PETEEEBOT_ENABLE_HSTS=true
```

The API applies baseline response headers: `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and production HSTS.

### 7.3 Machine API-key scope

`PETEEEBOT_API_KEY` is for machine actors only, such as private GPT actions, internal automation, and smoke checks. It is accepted only on the explicit machine API route set documented in `docs/api_endpoint_inventory.md`; browser auth endpoints such as `/auth/login`, `/auth/logout`, and `/auth/session` do not accept it.

Browser users should use session cookies and RBAC. Read-only users can read summaries/plans/logs; command endpoints such as `/sync`, `/run_pete_plan_async`, and nutrition writes require an `operator` or `owner` session. Machine API-key calls remain available for the listed machine endpoints and are not treated as browser users.

### 7.4 Machine API-key rotation

Use this procedure whenever the key may have leaked, after changing GPT/action clients, and on a regular maintenance cadence.

1. Generate a new high-entropy key on the host:

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

2. Update `PETEEEBOT_API_KEY` in `/home/ricwheatley/pete-eebot/.env`. Do not commit the value.
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

