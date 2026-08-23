from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.contract

WRAPPER = Path("pete_e/resources/deploy-wrapper.sh").resolve()


def _bash_or_skip() -> str:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is unavailable on this platform")
    try:
        probe = subprocess.run(
            [bash, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("bash is not executable on this platform")
    if probe.returncode != 0:
        pytest.skip("bash is not executable on this platform")
    return bash


def _git(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    return completed.stdout.strip()


def _repository_with_two_main_commits(tmp_path: Path) -> tuple[Path, Path, str, str]:
    remote = tmp_path / "expected.git"
    checkout = tmp_path / "current"
    _git("init", "--bare", str(remote))
    _git("clone", str(remote), str(checkout))
    _git("config", "user.name", "Edge Test", cwd=checkout)
    _git("config", "user.email", "edge-test@example.invalid", cwd=checkout)

    tracked = checkout / "version.txt"
    tracked.write_text("signed\n", encoding="utf-8")
    _git("add", "version.txt", cwd=checkout)
    _git("commit", "-m", "signed commit", cwd=checkout)
    signed_sha = _git("rev-parse", "HEAD", cwd=checkout)
    _git("push", "origin", "HEAD:refs/heads/main", cwd=checkout)

    tracked.write_text("later branch tip\n", encoding="utf-8")
    _git("commit", "-am", "later branch update", cwd=checkout)
    later_sha = _git("rev-parse", "HEAD", cwd=checkout)
    _git("push", "origin", "HEAD:refs/heads/main", cwd=checkout)
    return remote, checkout, signed_sha, later_sha


def _wrapper_environment(
    tmp_path: Path,
    *,
    remote: Path,
    checkout: Path,
    signed_sha: str,
    tracked_deploy: Path,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PROJECT_ROOT": str(tmp_path),
            "APP_ROOT": str(checkout),
            "SHARED_ROOT": str(tmp_path / "shared"),
            "VENV_ROOT": str(tmp_path / "shared" / "venv"),
            "ENV_FILE": str(tmp_path / "shared" / ".env"),
            "LOGFILE": str(tmp_path / "deploy.log"),
            "LOCKFILE": str(tmp_path / "deploy.lock"),
            "TRACKED_DEPLOY": str(tracked_deploy),
            "WEBHOOK_DELIVERY_ID": "exact-sha-delivery",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_COMMIT_SHA": signed_sha,
            "GITHUB_REF": "refs/heads/main",
            "PETEEEBOT_DEPLOY_GIT_REMOTE": "origin",
            "PETEEEBOT_DEPLOY_GIT_REMOTE_URL": str(remote),
            "PETEEEBOT_GITHUB_DEPLOY_REF": "refs/heads/main",
        }
    )
    return environment


def test_wrapper_selects_signed_sha_even_after_main_advances(tmp_path: Path) -> None:
    bash = _bash_or_skip()
    remote, checkout, signed_sha, later_sha = _repository_with_two_main_commits(tmp_path)
    observed = tmp_path / "observed-head.txt"
    harmless_deploy = tmp_path / "harmless-deploy.sh"
    harmless_deploy.write_text(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\ngit rev-parse HEAD > \"${OUTPUT_FILE}\"\n",
        encoding="utf-8",
    )
    harmless_deploy.chmod(0o700)
    environment = _wrapper_environment(
        tmp_path,
        remote=remote,
        checkout=checkout,
        signed_sha=signed_sha,
        tracked_deploy=harmless_deploy,
    )
    environment["OUTPUT_FILE"] = str(observed)

    completed = subprocess.run(
        [bash, str(WRAPPER)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert signed_sha != later_sha
    assert observed.read_text(encoding="utf-8").strip() == signed_sha
    assert _git("rev-parse", "HEAD", cwd=checkout) == signed_sha


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("GITHUB_COMMIT_SHA", "$(touch command-injection-marker)"),
        ("GITHUB_REF", "refs/heads/main;touch command-injection-marker"),
    ],
)
def test_wrapper_rejects_command_injection_shaped_metadata(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    bash = _bash_or_skip()
    remote, checkout, signed_sha, _later_sha = _repository_with_two_main_commits(tmp_path)
    harmless_deploy = tmp_path / "harmless-deploy.sh"
    harmless_deploy.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    harmless_deploy.chmod(0o700)
    environment = _wrapper_environment(
        tmp_path,
        remote=remote,
        checkout=checkout,
        signed_sha=signed_sha,
        tracked_deploy=harmless_deploy,
    )
    environment[field] = value

    completed = subprocess.run(
        [bash, str(WRAPPER)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert not (tmp_path / "command-injection-marker").exists()
