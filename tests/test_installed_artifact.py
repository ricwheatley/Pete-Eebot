"""Smoke the built wheel from an environment outside the source checkout."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

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


def _artifact_environment(tmp_path: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
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
            "PETE_LOG_TO_CONSOLE": "false",
        }
    )
    return environment


def test_built_wheel_cli_api_and_resources_outside_checkout(tmp_path: Path) -> None:
    build_source = tmp_path / "build-source"
    build_source.mkdir()
    shutil.copytree(
        ROOT / "pete_e",
        build_source / "pete_e",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(ROOT / "pyproject.toml", build_source / "pyproject.toml")
    shutil.copy2(ROOT / "README.md", build_source / "README.md")

    wheel_dir = tmp_path / "wheelhouse"
    wheel_dir.mkdir()
    build = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from setuptools.build_meta import build_wheel; "
                f"print(build_wheel({str(wheel_dir)!r}))"
            ),
        ],
        cwd=build_source,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheel = next(wheel_dir.glob("pete_e-*.whl"))

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

    smoke_script = f"""
import asyncio
from importlib.resources import files
from pathlib import Path

import pete_e
from pete_e.api import app
from pete_e.api_routes.status_sync import healthz

module_path = Path(pete_e.__file__).resolve()
assert Path({str(ROOT)!r}) not in module_path.parents, module_path
assert (files('pete_e') / 'resources' / 'phrases_tagged.json').is_file()
assert (files('pete_e') / 'templates' / 'console' / 'base.html').is_file()

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
