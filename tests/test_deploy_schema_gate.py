from pathlib import Path


def test_deploy_gates_restart_on_preflight_backup_upgrade_and_verification() -> None:
    script = Path("pete_e/resources/deploy.sh").read_text(encoding="utf-8")

    preflight = script.index("-m pete_e.cli.schema preflight")
    backup = script.index("scripts/backup_db.sh")
    upgrade = script.index("-m pete_e.cli.schema upgrade")
    verify = script.index("-m pete_e.cli.schema verify")
    cron = script.index("-m pete_e.infrastructure.cron_manager")
    restart = script.index('restart_service\n')

    assert "set -Eeuo pipefail" in script
    assert preflight < backup < upgrade < verify < cron < restart


def test_deploy_never_logs_migrator_connection_string() -> None:
    script = Path("pete_e/resources/deploy.sh").read_text(encoding="utf-8")

    assert "PETEEEBOT_MIGRATOR_DATABASE_URL" not in script


def test_deploy_wrapper_selects_and_validates_exact_signed_sha() -> None:
    wrapper = Path("pete_e/resources/deploy-wrapper.sh").read_text(encoding="utf-8")
    tracked = Path("pete_e/resources/deploy.sh").read_text(encoding="utf-8")

    assert 'git reset --hard "${GITHUB_COMMIT_SHA}"' in wrapper
    assert 'git merge-base --is-ancestor "${GITHUB_COMMIT_SHA}"' in wrapper
    assert 'git cat-file -e "${GITHUB_COMMIT_SHA}^{commit}"' in wrapper
    assert 'ACTUAL_REMOTE_URL="$(git remote get-url "${DEPLOY_GIT_REMOTE}")"' in wrapper
    assert "git reset --hard origin/main" not in wrapper
    assert 'CURRENT_HEAD="$(git rev-parse HEAD)"' in tracked
    assert '"${CURRENT_HEAD}" == "${GITHUB_COMMIT_SHA}"' in tracked


def test_systemd_deployment_worker_is_independent_from_api_service() -> None:
    api_unit = Path("pete_e/resources/peteeebot.service").read_text(encoding="utf-8")
    deploy_unit = Path("pete_e/resources/peteeebot-deploy@.service").read_text(encoding="utf-8")
    active_directives = {
        line.strip()
        for line in deploy_unit.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "KillMode=control-group" in api_unit
    assert "KillMode=control-group" in deploy_unit
    assert "Restart=no" in deploy_unit
    assert "TimeoutStartSec=infinity" in deploy_unit
    assert any(line.startswith("ExecStart=") and "pete_e.deployment_worker %i" in line for line in active_directives)
    assert not any(line.startswith(("PartOf=", "BindsTo=")) for line in active_directives)


def test_deployment_dispatch_helper_accepts_only_safe_job_ids_and_starts_template() -> None:
    helper = Path("pete_e/resources/peteeebot-dispatch-deploy").read_text(encoding="utf-8")
    sudoers = Path("pete_e/resources/peteeebot-deploy.sudoers").read_text(encoding="utf-8")

    assert "^[A-Za-z0-9_.-]+$" in helper
    assert "/bin/systemctl start --no-block" in helper
    assert '"peteeebot-deploy@${job_id}.service"' in helper
    assert "/usr/local/sbin/peteeebot-dispatch-deploy *" in sudoers
    assert "/bin/systemctl restart peteeebot.service" in sudoers


def test_systemd_installer_does_not_start_or_restart_services() -> None:
    installer = Path("pete_e/resources/install-systemd-units.sh").read_text(encoding="utf-8")

    assert "/bin/systemctl daemon-reload" in installer
    assert "systemctl start" not in installer
    assert "systemctl restart" not in installer


def test_host_topology_runbook_uses_a_harmless_exec_override_and_bounded_waits() -> None:
    runbook = Path("docs/job_ownership_deployment_runbook.md").read_text(encoding="utf-8")

    assert "Environment=DEPLOY_SCRIPT_PATH=/run/peteeebot-deploy-topology-test.sh" not in runbook
    assert (
        "ExecStart=/usr/bin/env DEPLOY_SCRIPT_PATH=/run/peteeebot-deploy-topology-test.sh"
        in runbook
    )
    assert "Controlled deployment did not start within 30 seconds." in runbook
    assert "Controlled deployment did not finish within 90 seconds." in runbook
    assert "until sudo test -e /run/peteeebot-deploy-topology.started" not in runbook
