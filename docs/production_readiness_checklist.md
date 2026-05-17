# Production Readiness Checklist

Last updated: 2026-05-15.

Use this checklist before exposing Pete-Eebot to production traffic or before a material production change such as a new host, reverse proxy change, auth change, schema migration, backup change, or alerting change. Record evidence in the release notes or in a copied signoff from `docs/production_readiness_signoff_template.md`.

Reference docs:

- `docs/runtime_deploy_runbook.md` for deploy, smoke-check, backup, security, and alert response commands.
- `docs/logging_observability.md` for JSON log fields, metrics, probes, and triage workflow.
- `docs/operator_guide.md` for operator workflows and first-time setup.
- `docs/api_endpoint_inventory.md` for route auth expectations.

## Readiness Gates

Production is ready only when every required item below is checked, has an owner, and has evidence. If an item is deliberately deferred, record the residual risk, expiry date, and fallback in the signoff.

Severity guidance:

- **Blocker:** do not expose or continue production traffic.
- **High:** acceptable only for a time-boxed controlled rollout with an explicit fallback.
- **Medium:** acceptable with owner and follow-up date.

## 1. Deployment Prerequisites

| Check | Severity | Evidence |
| --- | --- | --- |
| [ ] Target commit, branch, and release identifier are recorded. | Blocker | Git SHA, branch, deploy time. |
| [ ] Supported runtime profile is confirmed: native Python virtual environment on Ubuntu with Postgres reachable from the host. | Blocker | Host name, OS, Python version, Postgres version. |
| [ ] Application container image is not used as the production runtime unless a new supported Dockerfile/runbook has been created and reviewed. | Blocker | Deployment profile note. |
| [ ] Production layout matches the runbook: `.env`, `venv`, `deploy.sh`, `app`, and backup directories live outside the Git cleanup boundary where expected. | Blocker | Path listing or operator confirmation. |
| [ ] `.env` is present only on the host, not committed, and has owner-only permissions where practical. | Blocker | `ls -l` output with secrets redacted. |
| [ ] Required environment values are populated: Postgres, Dropbox, Withings, Telegram if enabled, wger if enabled, `PETEEEBOT_API_KEY`, `GITHUB_WEBHOOK_SECRET`, and `DEPLOY_SCRIPT_PATH`. | Blocker | Redacted env inventory. |
| [ ] Python dependencies install cleanly from `requirements.txt` and the package installs with `pip install --no-deps -e .`. | Blocker | Install log summary. |
| [ ] Database schema baseline and all intended migrations have been applied in order. | Blocker | Applied SQL list and DB target. |
| [ ] Migration rollback or restore path is known before applying any migration that changes production data. | Blocker | Rollback section in release note. |
| [ ] `python -m scripts.check_auth` and `pete status` complete with expected provider status. | Blocker | Command output summary. |
| [ ] Cron source of truth has been rendered/applied from `pete_e/resources/pete_crontab.csv`; disabled missing-script rows remain disabled. | High | Cron summary output. |
| [ ] `peteeebot.service` exists, runs under the intended user, and is managed by systemd. | Blocker | `systemctl status` summary. |
| [ ] Deploy webhook path is configured to run the stable wrapper script outside the checkout, then the tracked deploy script. | High | Redacted `DEPLOY_SCRIPT_PATH` and wrapper path. |
| [ ] Post-deploy smoke checks from `docs/runtime_deploy_runbook.md` pass: CLI status, systemd active, sync dry run/short run, Telegram listener if enabled, local `/healthz`, local `/readyz`, local `/api/v1/status`, local `/api/v1/metrics`, public HTTPS `/healthz`, public HTTPS authenticated `/api/v1/status`, and direct public app-port denial. | Blocker | Smoke-check transcript or summary. |

## 2. TLS and Reverse Proxy Expectations

| Check | Severity | Evidence |
| --- | --- | --- |
| [ ] Public ingress terminates TLS at a maintained reverse proxy such as Caddy or Nginx. | Blocker | Proxy config path and cert issuer. |
| [ ] The FastAPI/Uvicorn application binds to `127.0.0.1` or a private interface only. Direct public access to the app port is blocked. | Blocker | Service command and firewall/proxy evidence. |
| [ ] Only intended public ports are reachable from the internet, normally `80` for redirect/ACME and `443` for HTTPS. | Blocker | Firewall or port scan result. |
| [ ] HTTP redirects to HTTPS. | Blocker | `curl -I http://...` result. |
| [ ] Certificate automation and renewal monitoring are in place. | High | ACME/certbot/Caddy status and renewal date. |
| [ ] HSTS is enabled for production once HTTPS is confirmed stable: `PETEEEBOT_ENABLE_HSTS=true`. | High | Response header evidence. |
| [ ] Reverse proxy forwards `Host`, scheme, and client IP headers required for accurate request logging and secure redirects. | High | Proxy config excerpt. |
| [ ] Request body size, header size, and upstream timeout limits are set to conservative values for the API and webhook surface. | High | Proxy limit values. |
| [ ] `/readyz` returns only coarse unauthenticated readiness; detailed dependency names/errors require authenticated `/api/v1/status` or `/console/status`. | High | Public `/readyz` sample plus authenticated status sample. |
| [ ] `/api/v1/metrics` remains authenticated and is scraped with `X-API-Key` or a trusted authenticated session. | High | Scrape config. |
| [ ] GitHub webhook route is reachable only as needed and still relies on `X-Hub-Signature-256` HMAC validation. | High | Webhook test result. |

## 3. Auth, Session, and Security Controls

| Check | Severity | Evidence |
| --- | --- | --- |
| [ ] `PETEEEBOT_API_KEY` is high entropy, stored only in secret locations, and used only by machine clients. | Blocker | Rotation date and client inventory. |
| [ ] Old machine API keys fail after any key rotation. | High | `401` verification result. |
| [ ] First browser owner was created with `pete bootstrap-owner`; no password hash was hand-written and no public bootstrap route is exposed. | Blocker | Command transcript with secret redacted and owner username. |
| [ ] Owner password recovery was tested with `pete reset-owner-password` or explicitly deferred with a named break-glass owner. | High | Reset test summary or deferred-risk note. |
| [ ] Browser login is used for human users; machine API key is not accepted as a substitute for browser auth on auth/session routes. | High | Route inventory or test evidence. |
| [ ] Production session cookies are secure: `PETEEEBOT_SESSION_COOKIE_SECURE=true`, `PETEEEBOT_SESSION_COOKIE_SAMESITE=lax`, and no broad cookie domain unless required. | Blocker | Redacted env and response cookie evidence. |
| [ ] State-changing browser requests require CSRF token validation. | Blocker | Manual or automated request evidence. |
| [ ] Login rate limiting and lockout settings are configured and tested. | High | Failed-login test summary. |
| [ ] RBAC is enforced: read-only users cannot run command endpoints; `operator` or `owner` role is required for high-risk operations. | Blocker | Authz test summary. |
| [ ] CORS is fail-closed for same-origin deployment or explicitly allowlisted for a known separate UI origin. | High | `PETEEEBOT_CORS_ALLOWED_ORIGINS` value. |
| [ ] Security headers are present: CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and production HSTS. | High | `curl -I` result. |
| [ ] Webhook secret is configured and signature failure returns unauthorized without starting deploy. | Blocker | Negative webhook test summary. |
| [ ] Provider secrets and refresh tokens have owner-only permissions where possible and are excluded from backup locations that are not encrypted. | Blocker | Redacted path/permission evidence. |
| [ ] Backup encryption key or passphrase is stored outside the repo and recoverable by the operator. | Blocker | Password manager/key-file location confirmation. |

## 4. Backup and Restore Validation

| Check | Severity | Evidence |
| --- | --- | --- |
| [ ] `scripts/backup_db.sh` runs successfully on demand in the production environment. | Blocker | Backup log path and timestamp. |
| [ ] Latest local Postgres dump exists outside the Git checkout at the expected path. | Blocker | `latest.dump` path and size. |
| [ ] Secret backup copies exist outside the Git checkout and have restricted permissions. | Blocker | Redacted path/permission evidence. |
| [ ] If cloud backup is enabled, encrypted artifacts upload successfully to the expected Dropbox directory. | High | Upload log and remote path. |
| [ ] Encrypted cloud backup can be decrypted with the retained key or passphrase. | Blocker if cloud backup is primary | Decrypt test output. |
| [ ] Restore has been validated into a disposable database or fresh host, not only by checking that a dump file exists. | Blocker | Restore target, timestamp, and result. |
| [ ] Restored database passes basic sanity checks: expected tables exist, recent health/workout/nutrition rows are present, and `pete status` can connect. | Blocker | Query summaries and command result. |
| [ ] Restore procedure includes `.env`, Withings token file, and any other required local runtime secrets. | Blocker | Restore checklist evidence. |
| [ ] RPO and RTO are documented for the release. | High | RPO/RTO values in signoff. |
| [ ] Backup schedule is installed and logs are reviewed after the next scheduled run. | High | Cron row and follow-up owner. |

## 5. Observability and Alert Tests

| Check | Severity | Evidence |
| --- | --- | --- |
| [ ] Production logs use JSON format: `PETE_LOG_FORMAT=json`. | Blocker | Env value and sample log line. |
| [ ] Logs are written to the intended path and rotate or are otherwise bounded. | High | Path, size, rotation setting. |
| [ ] API responses include `X-Request-ID` and `X-Correlation-ID`; those IDs appear in JSON logs. | High | Request/log correlation sample. |
| [ ] Background jobs emit `background_job` structured records with operation, outcome, duration, and job ID. | High | Sample log record. |
| [ ] `/healthz` returns liveness without dependency checks. | High | `curl` result. |
| [ ] `/readyz?timeout=5` returns only coarse `healthy`/`unhealthy` readiness and fails with `503` when a required dependency is unhealthy. | High | Healthy result plus known-failure or staging negative test. |
| [ ] `/api/v1/status?timeout=5` is authenticated and returns expected operational summary. | Blocker | Authenticated response summary. |
| [ ] `/api/v1/metrics` exposes Prometheus metrics with authentication. | High | Scrape sample. |
| [ ] Key metrics are present: job runs/failures/durations/retries, dependency health, external API health, alert events, and active alerts. | High | Metrics sample. |
| [ ] Telegram alerting is enabled if expected: `PETEEEBOT_ALERT_TELEGRAM_ENABLED=true`. | High | Redacted env value. |
| [ ] Alert dedupe and thresholds are intentionally configured: stale ingest days, repeated failure threshold, and dedupe seconds. | High | Redacted env values. |
| [ ] At least one alert path has been tested in staging or by a controlled production-safe trigger, with delivery, log event, metric increment, and dedupe behavior verified. | High | Alert test notes. |
| [ ] Heartbeat check can detect and restart a failed `peteeebot.service`, or the decision not to auto-restart is explicitly documented. | High | Heartbeat test or risk record. |
| [ ] Operator triage path works without shell access where intended: `/console/status`, `/console/logs?lines=200`, `/console/operations`, and `/console/trends`. | Medium | Browser/API check summary. |

## 6. Rollback Plan

| Check | Severity | Evidence |
| --- | --- | --- |
| [ ] Previous known-good Git SHA and deploy timestamp are recorded before deployment. | Blocker | SHA and timestamp. |
| [ ] Rollback command sequence is written for the current host and does not depend on memory during an incident. | Blocker | Release-specific rollback note. |
| [ ] Rollback trigger criteria are defined: failed smoke checks, failed auth, failing migrations, elevated 5xx, broken sync, broken daily message, or failed dependency readiness. | High | Criteria in signoff. |
| [ ] Database rollback strategy is explicit: restore from predeploy backup, apply down SQL/manual correction, or accept forward-only migration with documented compatibility. | Blocker | DB rollback decision. |
| [ ] A fresh predeploy backup has completed before applying any schema or destructive data change. | Blocker | Backup timestamp. |
| [ ] Feature flags and environment toggles can be reverted independently of code where applicable. | High | Flag/env rollback list. |
| [ ] Reverse proxy config has a known-good copy and can be reloaded or restored independently. | High | Config backup path. |
| [ ] API key/session/security changes include a recovery path for locked-out operators using `pete reset-owner-password` and lockout wait/restart guidance from the runbook. | High | Break-glass note. |
| [ ] Rollback smoke checks reuse the same post-deploy checks from the runbook. | Blocker | Smoke-check checklist link. |
| [ ] Communication path is defined for rollback completion and residual risk. | Medium | Telegram/operator note. |

### Minimal Code Rollback Example

Adapt paths and service names to the host:

```bash
cd /opt/myapp/current
git fetch --all --prune
git reset --hard <previous-known-good-sha>
/opt/myapp/shared/venv/bin/python -m pip install --no-deps -e .
sudo systemctl restart peteeebot.service
```

Then run the smoke checks in `docs/runtime_deploy_runbook.md`.

Do not use code rollback alone if the release applied incompatible database changes. Restore or correct the database first, or roll forward with a compatible fix.
