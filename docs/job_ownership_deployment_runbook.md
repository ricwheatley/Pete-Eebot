# Job ownership and independent deployment verification

## First rollout

Do not use the old webhook child process to roll out this remediation. Quiesce
webhook/manual high-risk commands, confirm no current jobs or operation lock,
install and validate the units/helper from the reviewed candidate checkout,
then run the stable wrapper once from a separate administrator-started systemd
unit. The schema migration backfills an active legacy lock, but a quiesced
rollout avoids mixing old unfenced code with the new lock columns.

```bash
sudo bash /path/to/reviewed-candidate/pete_e/resources/install-systemd-units.sh \
  /path/to/reviewed-candidate/pete_e/resources
sudo systemd-analyze verify /etc/systemd/system/peteeebot.service \
  /etc/systemd/system/peteeebot-deploy@.service
BOOTSTRAP_SHA="$(git -C /path/to/reviewed-candidate rev-parse HEAD)"
sudo systemd-run --unit=peteeebot-bootstrap-deploy --collect --wait \
  --property=User=deploy --property=Group=deploy \
  --property=WorkingDirectory=/opt/myapp/current \
  --property=EnvironmentFile=/opt/myapp/shared/.env \
  --setenv=GITHUB_EVENT_NAME=push \
  --setenv=GITHUB_REF=refs/heads/main \
  --setenv=GITHUB_COMMIT_SHA="${BOOTSTRAP_SHA}" \
  /opt/myapp/scripts/deploy.sh
```

Review `systemctl status peteeebot-bootstrap-deploy` and the durable job tables
before re-enabling webhook/manual deployment.

## Crash and retry behavior

The API creates token 1 only for dispatch. The independent unit atomically
takes ownership as token 2 and renews the job and lock together. If dispatch
fails, token 1 records failure and deletes its matching lock. If the deploy
worker or host crashes after handoff, its lease expires; periodic API recovery
marks the job abandoned and deletes only token 2's lock. Retry creates a new job
because migration, package installation, Git update, and service restart are not
generally safe to replay automatically after an unknown interruption point.

## Controlled API-restart topology verification (Ubuntu host)

Run this after installation on the target Ubuntu system. It substitutes a
harmless blocking script for one specific deploy-unit instance, so it does not
fetch Git, migrate, install, or perform a real deployment.

```bash
export TEST_JOB_ID="deploy-host-topology-$(date +%Y%m%d%H%M%S)"
sudo rm -f /run/peteeebot-deploy-topology.started \
  /run/peteeebot-deploy-topology.release
sudo tee /run/peteeebot-deploy-topology-test.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
touch /run/peteeebot-deploy-topology.started
while [[ ! -e /run/peteeebot-deploy-topology.release ]]; do sleep 0.2; done
printf '%s\n' "controlled deployment worker completed"
EOF
sudo chmod 0755 /run/peteeebot-deploy-topology-test.sh
sudo mkdir -p "/etc/systemd/system/peteeebot-deploy@${TEST_JOB_ID}.service.d"
sudo tee "/etc/systemd/system/peteeebot-deploy@${TEST_JOB_ID}.service.d/override.conf" >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/env DEPLOY_SCRIPT_PATH=/run/peteeebot-deploy-topology-test.sh /opt/myapp/shared/venv/bin/python3 -m pete_e.deployment_worker %i
EOF
sudo systemctl daemon-reload
sudo systemctl cat "peteeebot-deploy@${TEST_JOB_ID}.service"
sudo systemctl show "peteeebot-deploy@${TEST_JOB_ID}.service" -p ExecStart
```

The instance-specific `ExecStart=` reset is intentional. The base unit's
`EnvironmentFile=` may define `DEPLOY_SCRIPT_PATH`, and systemd gives values
read from an environment file precedence over `Environment=` assignments. The
effective unit output above must show `/usr/bin/env` setting the harmless path
on the worker command line before continuing.

Dispatch the fixed test job through the same durable handoff and root-owned
helper used by the API:

```bash
sudo -u deploy env TEST_JOB_ID="$TEST_JOB_ID" bash -lc '
set -a; . /opt/myapp/shared/.env; set +a
cd /opt/myapp/current
/opt/myapp/shared/venv/bin/python3 - <<"PY"
import os
from pete_e.application.jobs import ApplicationJobService
from pete_e.config import settings
from pete_e.infrastructure.job_repository import PostgresApplicationJobRepository

job_id = os.environ["TEST_JOB_ID"]
service = ApplicationJobService(
    PostgresApplicationJobRepository(),
    lease_seconds=settings.PETEEEBOT_JOB_LEASE_SECONDS,
    heartbeat_interval_seconds=settings.PETEEEBOT_JOB_HEARTBEAT_SECONDS,
    recovery_interval_seconds=settings.PETEEEBOT_JOB_RECOVERY_SECONDS,
)
try:
    service.dispatch_external(
        job_id=job_id,
        operation="deploy",
        dispatch_command=["sudo", "-n", str(settings.PETEEEBOT_DEPLOY_DISPATCH_BIN), job_id],
        requester=None,
        request_id=job_id,
        correlation_id=job_id,
        request_summary={"source": "controlled_host_topology_test"},
    )
finally:
    service.close(wait=False)
PY
'
TEST_STARTED=0
for attempt in {1..150}; do
  if sudo test -e /run/peteeebot-deploy-topology.started; then
    TEST_STARTED=1
    break
  fi
  sleep 0.2
done
if [[ "${TEST_STARTED}" != "1" ]]; then
  sudo systemctl status "peteeebot-deploy@${TEST_JOB_ID}.service" --no-pager || true
  sudo journalctl -u "peteeebot-deploy@${TEST_JOB_ID}.service" --no-pager -n 100
  printf '%s\n' "Controlled deployment did not start within 30 seconds." >&2
  exit 1
fi
sudo systemctl show peteeebot.service \
  "peteeebot-deploy@${TEST_JOB_ID}.service" -p Id -p MainPID -p ControlGroup
sudo systemctl restart peteeebot.service
sudo systemctl is-active peteeebot.service
sudo systemctl is-active "peteeebot-deploy@${TEST_JOB_ID}.service"
sudo touch /run/peteeebot-deploy-topology.release
TEST_FINISHED=0
for attempt in {1..450}; do
  if ! sudo systemctl is-active --quiet "peteeebot-deploy@${TEST_JOB_ID}.service"; then
    TEST_FINISHED=1
    break
  fi
  sleep 0.2
done
if [[ "${TEST_FINISHED}" != "1" ]]; then
  sudo systemctl status "peteeebot-deploy@${TEST_JOB_ID}.service" --no-pager || true
  sudo journalctl -u "peteeebot-deploy@${TEST_JOB_ID}.service" --no-pager -n 100
  printf '%s\n' "Controlled deployment did not finish within 90 seconds." >&2
  exit 1
fi
```

Require different non-empty `ControlGroup` values before restart, and require
the deploy unit to remain `active` immediately after the API restart. Finally,
verify durable terminal state and exact lock cleanup:

```bash
sudo -u deploy env TEST_JOB_ID="$TEST_JOB_ID" bash -lc '
set -a; . /opt/myapp/shared/.env; set +a
cd /opt/myapp/current
/opt/myapp/shared/venv/bin/python3 - <<"PY"
import os
from pete_e.infrastructure.job_repository import PostgresApplicationJobRepository

repository = PostgresApplicationJobRepository()
job = repository.get(os.environ["TEST_JOB_ID"])
operation_lock = repository.get_active_high_risk_operation_lock()
print({"status": job.status if job else None, "active_lock": operation_lock})
assert job is not None and job.status == "succeeded"
assert operation_lock is None
PY
'
sudo rm -f \
  "/etc/systemd/system/peteeebot-deploy@${TEST_JOB_ID}.service.d/override.conf"
sudo rmdir "/etc/systemd/system/peteeebot-deploy@${TEST_JOB_ID}.service.d"
sudo rm -f /run/peteeebot-deploy-topology-test.sh \
  /run/peteeebot-deploy-topology.started \
  /run/peteeebot-deploy-topology.release
sudo systemctl daemon-reload
```

Record the job ID, both cgroups/PIDs, restart timestamp, terminal job row, lock
query, and relevant journals. This criterion remains pending until these commands
have run on the actual systemd-capable target.
