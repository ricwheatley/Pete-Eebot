"""Smoke the built wheel from an environment outside the source checkout."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tarfile
import venv
import zipfile

from click import unstyle
import pytest


pytestmark = pytest.mark.artifact
ROOT = Path(__file__).resolve().parents[1]


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_cli(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "pete.exe"
    return venv_dir / "bin" / "pete"


def _venv_schema_cli(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "pete-schema.exe"
    return venv_dir / "bin" / "pete-schema"


def _artifact_environment(tmp_path: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    for name in (
        "PETEEEBOT_CRON_SOURCE",
        "PETEEBOT_MIGRATIONS_DIR",
        "PETEEBOT_PHRASES_FILE",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "ENVIRONMENT": "testing",
            "PETEEEBOT_ENV_FILE": str(tmp_path / "does-not-exist.env"),
            "USER_DATE_OF_BIRTH": "1990-01-01",
            "USER_HEIGHT_CM": "180",
            "USER_GOAL_WEIGHT_KG": "80",
            "TELEGRAM_TOKEN": "artifact-test-token",
            "TELEGRAM_CHAT_ID": "123456",
            "WITHINGS_CLIENT_ID": "artifact-client",
            "WITHINGS_CLIENT_SECRET": "artifact-secret",
            "WITHINGS_REDIRECT_URI": "https://localhost/callback",
            "WITHINGS_REFRESH_TOKEN": "artifact-refresh",
            "WGER_API_KEY": "artifact-test-key",
            "DROPBOX_HEALTH_METRICS_DIR": "/health",
            "DROPBOX_WORKOUTS_DIR": "/workouts",
            "DROPBOX_APP_KEY": "artifact-dropbox-key",
            "DROPBOX_APP_SECRET": "artifact-dropbox-secret",
            "DROPBOX_REFRESH_TOKEN": "artifact-dropbox-refresh",
            "POSTGRES_USER": "pete_test",
            "POSTGRES_PASSWORD": "pete_test",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "1",
            "POSTGRES_DB": "pete_e_test_artifact",
            "DATABASE_URL": "postgresql://pete_test:pete_test@127.0.0.1:1/pete_e_test_artifact",
            "PETEEEBOT_API_KEY": "artifact-api-key",
            "PETEEEBOT_CRONTAB_OUTPUT": str(tmp_path / "state" / "pete_crontab.txt"),
            "PETE_LOG_TO_CONSOLE": "false",
        }
    )
    return environment


def _wheel_members(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def _sdist_members(path: Path) -> set[str]:
    with tarfile.open(path, "r:gz") as archive:
        names = {member.name for member in archive.getmembers() if member.isfile()}
    roots = {name.split("/", 1)[0] for name in names}
    assert len(roots) == 1, sorted(roots)
    root = roots.pop()
    return {name.removeprefix(f"{root}/") for name in names if name != root}


def _assert_artifact_contents(members: set[str], *, wheel: bool) -> None:
    required = {
        "pete_e/resources/phrases_tagged.json",
        "pete_e/resources/pete_crontab.csv",
        "pete_e/static/operator_console.css",
        "pete_e/static/operator_console.js",
        "pete_e/templates/auth/login.html",
        "pete_e/templates/console/base.html",
        "pete_e/migrations/manifest.json",
        "pete_e/migrations/00000000_initial_schema.sql",
        "pete_e/migrations/20260822_trust_public_edge.sql",
        "pete_e/migrations/20260823_restore_wger_workout_ingest.sql",
        "pete_e/migrations/20260825_require_percentage_targets.sql",
    }
    assert required <= members, sorted(required - members)

    expected_python_packages = {
        "pete_e",
        "pete_e.api_routes",
        "pete_e.application",
        "pete_e.application.workflows",
        "pete_e.cli",
        "pete_e.config",
        "pete_e.domain",
        "pete_e.infrastructure",
        "pete_e.infrastructure.mappers",
        "pete_e.migrations",
        "pete_e.utils",
    }
    actual_python_packages = {
        name.rsplit("/", 1)[0].replace("/", ".")
        for name in members
        if name.startswith("pete_e/") and name.endswith(".py")
    }
    assert actual_python_packages == expected_python_packages

    forbidden_prefixes = (
        ".agents/",
        ".eggs/",
        ".github/",
        ".venv/",
        "build/",
        "dist/",
        "docs/",
        "env/",
        "ENV/",
        "init-db/",
        "logs/",
        "mocks/",
        "patches/",
        "scripts/",
        "tests/",
        "venv/",
    )
    relative_members = members if not wheel else {
        name for name in members if not name.startswith("pete_e-1.0.0.dist-info/")
    }
    assert not {
        name
        for name in relative_members
        if name.startswith(forbidden_prefixes)
    }

    checkout_only_resources = {
        "pete_e/resources/531_Manual-DESKTOP-1FJ3ER8.pdf",
        "pete_e/resources/deploy-wrapper.sh",
        "pete_e/resources/deploy.sh",
        "pete_e/resources/install-systemd-units.sh",
        "pete_e/resources/peteeebot-deploy.sudoers",
        "pete_e/resources/peteeebot-deploy@.service",
        "pete_e/resources/peteeebot-dispatch-deploy",
        "pete_e/resources/peteeebot.service",
    }
    assert not checkout_only_resources.intersection(members)


def test_built_wheel_cli_api_and_resources_outside_checkout(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "uv",
            "build",
            "--out-dir",
            str(artifact_dir),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheel = next(artifact_dir.glob("pete_e-*.whl"))
    sdist = next(artifact_dir.glob("pete_e-*.tar.gz"))

    metadata_check = subprocess.run(
        [sys.executable, "-m", "twine", "check", str(wheel), str(sdist)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert metadata_check.returncode == 0, metadata_check.stdout + metadata_check.stderr

    wheel_members = _wheel_members(wheel)
    sdist_members = _sdist_members(sdist)
    _assert_artifact_contents(wheel_members, wheel=True)
    _assert_artifact_contents(sdist_members, wheel=False)

    metadata_name = next(
        name for name in wheel_members if name.endswith(".dist-info/METADATA")
    )
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(metadata_name).decode("utf-8")
    requires_python = next(
        line.partition(":")[2].strip()
        for line in metadata.splitlines()
        if line.startswith("Requires-Python:")
    )
    assert {item.strip() for item in requires_python.split(",")} == {
        ">=3.11",
        "<3.14",
    }

    environment_dir = tmp_path / "installed-environment"
    venv.EnvBuilder(with_pip=True).create(environment_dir)
    python = _venv_python(environment_dir)

    sync_environment = dict(os.environ)
    sync_environment.pop("VIRTUAL_ENV", None)
    sync_environment["UV_PROJECT_ENVIRONMENT"] = str(environment_dir)
    sync = subprocess.run(
        [
            sys.executable,
            "-m",
            "uv",
            "sync",
            "--frozen",
            "--no-dev",
            "--no-install-project",
        ],
        cwd=ROOT,
        env=sync_environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert sync.returncode == 0, sync.stdout + sync.stderr

    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "--force-reinstall",
            str(wheel),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    dependency_check = subprocess.run(
        [sys.executable, "-m", "uv", "pip", "check", "--python", str(python)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert dependency_check.returncode == 0, dependency_check.stdout + dependency_check.stderr

    environment = _artifact_environment(tmp_path)
    cli_cases = (
        (["--help"], "Usage"),
        (["status", "--help"], "--timeout"),
        (["withings-auth"], "https://account.withings.com/oauth2_user/authorize2"),
    )
    for arguments, expected in cli_cases:
        cli = subprocess.run(
            [str(_venv_cli(environment_dir)), *arguments],
            cwd=tmp_path,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert cli.returncode == 0, cli.stdout + cli.stderr
        assert expected in unstyle(cli.stdout)

    schema_cli = subprocess.run(
        [str(_venv_schema_cli(environment_dir)), "--help"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert schema_cli.returncode == 0, schema_cli.stdout + schema_cli.stderr
    assert "upgrade" in unstyle(schema_cli.stdout)

    smoke_script = f"""
import asyncio
from importlib.resources import files
from pathlib import Path

import pete_e
from pete_e.api import app
from pete_e.api_routes.status_sync import healthz
from pete_e.config import settings
from pete_e.domain.phrase_picker import load_phrases
from pete_e.infrastructure.cron_manager import CRON_CSV, CRON_TXT, build_crontab_from_csv
from pete_e.infrastructure.schema_migrations import head_revision, migrations_directory

module_path = Path(pete_e.__file__).resolve()
assert Path({str(ROOT)!r}) not in module_path.parents, module_path
assert (files('pete_e') / 'resources' / 'phrases_tagged.json').is_file()
assert (files('pete_e') / 'resources' / 'pete_crontab.csv').is_file()
assert (files('pete_e') / 'templates' / 'console' / 'base.html').is_file()
assert (files('pete_e') / 'static' / 'operator_console.css').is_file()
assert (files('pete_e') / 'migrations' / 'manifest.json').is_file()
assert settings.phrases_path.is_file()
assert len(load_phrases()) > 100
assert CRON_CSV.is_file()
assert 'pete morning-report --send' in build_crontab_from_csv()
assert Path({str(ROOT)!r}) not in Path(CRON_TXT).resolve().parents
assert Path({str(ROOT)!r}) not in Path(str(migrations_directory())).resolve().parents
assert head_revision() == '20260825_require_percentage_targets'

schema = app.openapi()
assert schema['info']['title'] == 'Pete-Eebot API'
assert '/healthz' in schema['paths']

async def startup_smoke():
    async with app.router.lifespan_context(app):
        assert healthz() == {{'ok': True, 'status': 'live'}}

asyncio.run(startup_smoke())
"""
    api_smoke = subprocess.run(
        [str(python), "-c", smoke_script],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert api_smoke.returncode == 0, api_smoke.stdout + api_smoke.stderr
