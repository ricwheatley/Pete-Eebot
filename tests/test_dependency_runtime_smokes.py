"""Real-framework smoke coverage for the locked operational interfaces."""

from __future__ import annotations

import importlib.metadata

from click import unstyle
from fastapi.testclient import TestClient
import pytest
from typer.testing import CliRunner

from pete_e import api
from pete_e.cli import messenger


pytestmark = pytest.mark.contract


def test_real_cli_help_paths_render_with_locked_typer_and_click() -> None:
    runner = CliRunner()

    root_help = runner.invoke(messenger.app, ["--help"], color=False)
    status_help = runner.invoke(messenger.app, ["status", "--help"], color=False)
    root_output = unstyle(root_help.output)
    status_output = unstyle(status_help.output)

    assert root_help.exit_code == 0, root_help.output
    assert "Usage: pete [OPTIONS] COMMAND [ARGS]" in root_output
    assert status_help.exit_code == 0, status_help.output
    assert "Usage: pete status [OPTIONS]" in status_output
    assert "--timeout" in status_output
    assert importlib.metadata.version("typer") == "0.27.1"
    assert importlib.metadata.version("click") == "8.4.2"


def test_real_cli_side_effect_free_command_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(messenger.settings, "WITHINGS_CLIENT_ID", "contract-client")
    monkeypatch.setattr(messenger.settings, "WITHINGS_REDIRECT_URI", "https://localhost/callback")

    result = CliRunner().invoke(messenger.app, ["withings-auth"], color=False)

    assert result.exit_code == 0, result.output
    assert "https://account.withings.com/oauth2_user/authorize2" in result.output
    assert "client_id=contract-client" in result.output


def test_real_api_startup_health_and_openapi() -> None:
    schema = api.app.openapi()

    assert schema["info"]["title"] == "Pete-Eebot API"
    assert "/healthz" in schema["paths"]
    assert "/api/v1/status" in schema["paths"]

    with TestClient(api.app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "live"}
