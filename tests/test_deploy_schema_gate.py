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
