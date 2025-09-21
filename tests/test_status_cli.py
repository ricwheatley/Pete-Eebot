import pete_e.cli.status as status
import pete_e.cli.messenger as messenger
from pete_e.cli.messenger import app
from pete_e.cli.status import CheckResult
from typer.testing import CliRunner


runner = CliRunner()


def test_status_cli_all_ok(monkeypatch):
    """CLI exits with code 0 when all dependencies are healthy."""
    stub = lambda *, timeout=status.DEFAULT_TIMEOUT_SECONDS, checks=None: [
        CheckResult("DB", True, "3ms"),
        CheckResult("Dropbox", True, "demo@account"),
        CheckResult("Withings", True, "scale reachable"),
    ]
    monkeypatch.setattr(status, "run_status_checks", stub)
    monkeypatch.setattr(messenger, "run_status_checks", stub)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "DB" in result.stdout
    assert "Dropbox" in result.stdout
    assert "Withings" in result.stdout
    assert "OK" in result.stdout


def test_status_cli_failure_propagates(monkeypatch):
    """CLI exits with non-zero when any dependency fails."""
    captured = {}

    def fake_checks(*, timeout, checks=None):
        captured["timeout"] = timeout
        return [
            CheckResult("DB", False, "connection refused"),
            CheckResult("Dropbox", True, "demo"),
            CheckResult("Withings", True, "scale reachable"),
        ]

    monkeypatch.setattr(status, "run_status_checks", fake_checks)
    monkeypatch.setattr(messenger, "run_status_checks", fake_checks)

    result = runner.invoke(app, ["status", "--timeout", "2.5"])

    assert result.exit_code == 1
    assert "FAIL" in result.stdout
    assert "connection refused" in result.stdout
    assert captured["timeout"] == 2.5
