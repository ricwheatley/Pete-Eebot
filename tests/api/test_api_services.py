import asyncio
import hashlib
import hmac
import sys
import types
from unittest.mock import MagicMock

import pytest


if "fastapi" not in sys.modules:
    fastapi_module = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str | None = None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
            """Initialize this object."""
        """Represent HTTPException."""

    class Request:
        def __init__(self, query_params: dict | None = None):
            self.query_params = query_params or {}
            """Initialize this object."""
        """Represent Request."""

    def _identity(value=None, **kwargs):
        return value
        """Perform identity."""

    class FastAPI:
        def __init__(self, *args, **kwargs):
            pass
            """Initialize this object."""

        def get(self, *args, **kwargs):
            def decorator(func):
                return func
                """Perform decorator."""
            return decorator
            """Perform get."""

        def post(self, *args, **kwargs):
            def decorator(func):
                return func
                """Perform decorator."""
            return decorator
            """Perform post."""
        """Represent FastAPI."""

    fastapi_module.FastAPI = FastAPI
    fastapi_module.Query = _identity
    fastapi_module.Header = _identity
    fastapi_module.HTTPException = HTTPException
    fastapi_module.Request = Request

    responses_module = types.ModuleType("fastapi.responses")

    class StreamingResponse:  # pragma: no cover - compatibility with api module
        def __init__(self, content, media_type=None):
            self.content = content
            self.media_type = media_type
            """Initialize this object."""
        """Represent StreamingResponse."""

    responses_module.StreamingResponse = StreamingResponse

    sys.modules["fastapi"] = fastapi_module
    sys.modules["fastapi.responses"] = responses_module


from pete_e import api


@pytest.fixture()
def request_stub() -> api.Request:
    return api.Request({})
    """Perform request stub."""


@pytest.fixture()
def enable_api_key(monkeypatch):
    monkeypatch.setattr(api.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)
    """Perform enable api key."""


def test_metrics_overview_uses_service(monkeypatch, enable_api_key, request_stub):
    expected = {"columns": ["col1", "col2"], "rows": [[1, 2], [3, 4]]}
    service = MagicMock()
    service.overview.return_value = expected

    monkeypatch.setattr(api, "get_metrics_service", lambda: service)

    response = api.metrics_overview(request=request_stub, date="2024-01-01", x_api_key="test-key")

    assert response == expected
    service.overview.assert_called_once_with("2024-01-01")
    """Perform test metrics overview uses service."""


def test_coach_state_uses_service(monkeypatch, enable_api_key, request_stub):
    expected = {"summary": {"readiness_state": "green"}}
    service = MagicMock()
    service.coach_state.return_value = expected

    monkeypatch.setattr(api, "get_metrics_service", lambda: service)

    response = api.coach_state(request=request_stub, date="2024-01-08", x_api_key="test-key")

    assert response == expected
    service.coach_state.assert_called_once_with("2024-01-08")
    """Perform test coach state uses service."""


def test_recent_workouts_uses_service(monkeypatch, enable_api_key, request_stub):
    expected = {"running": [], "strength": []}
    service = MagicMock()
    service.recent_workouts.return_value = expected

    monkeypatch.setattr(api, "get_metrics_service", lambda: service)

    response = api.recent_workouts(
        request=request_stub,
        days=7,
        end_date="2024-01-08",
        x_api_key="test-key",
    )

    assert response == expected
    service.recent_workouts.assert_called_once_with(days=7, iso_end_date="2024-01-08")
    """Perform test recent workouts uses service."""


def test_plan_for_day_uses_service(monkeypatch, enable_api_key, request_stub):
    expected = {"columns": ["col"], "rows": [["value"]]}
    service = MagicMock()
    service.for_day.return_value = expected

    monkeypatch.setattr(api, "get_plan_service", lambda: service)

    response = api.plan_for_day(request=request_stub, date="2024-02-02", x_api_key="test-key")

    assert response == expected
    service.for_day.assert_called_once_with("2024-02-02")
    """Perform test plan for day uses service."""


def test_plan_for_week_uses_service(monkeypatch, enable_api_key, request_stub):
    expected = {"columns": ["col"], "rows": [["value"]]}
    service = MagicMock()
    service.for_week.return_value = expected

    monkeypatch.setattr(api, "get_plan_service", lambda: service)

    response = api.plan_for_week(request=request_stub, start_date="2024-02-05", x_api_key="test-key")

    assert response == expected
    service.for_week.assert_called_once_with("2024-02-05")
    """Perform test plan for week uses service."""


def test_status_requires_api_key_configuration(monkeypatch, request_stub):
    monkeypatch.setattr(api.settings, "PETEEEBOT_API_KEY", None, raising=False)

    with pytest.raises(api.HTTPException) as exc:
        api.status(request=request_stub, x_api_key="test-key")

    assert exc.value.status_code == 503
    """Perform test status requires api key configuration."""


def test_github_webhook_uses_configured_secret_and_deploy_path(monkeypatch, tmp_path):
    body = b'{"ref":"refs/heads/main"}'
    deploy_script = tmp_path / "deploy.sh"
    deploy_script.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(api.settings, "GITHUB_WEBHOOK_SECRET", "hook-secret", raising=False)
    monkeypatch.setattr(api.settings, "DEPLOY_SCRIPT_PATH", deploy_script, raising=False)

    popen_calls: list[list[str]] = []
    monkeypatch.setattr(api.subprocess, "Popen", lambda args: popen_calls.append(args))

    signature = hmac.new(b"hook-secret", msg=body, digestmod=hashlib.sha256).hexdigest()

    class WebhookRequest:
        headers = {"X-Hub-Signature-256": f"sha256={signature}"}

        async def body(self):
            return body
            """Perform body."""
        """Represent WebhookRequest."""

    payload = asyncio.run(api.github_webhook(WebhookRequest()))

    assert payload["status"] == "Deployment triggered"
    assert popen_calls == [[str(deploy_script)]]
    """Perform test github webhook uses configured secret and deploy path."""


def test_api_module_has_no_psycopg_import():
    assert not hasattr(api, "psycopg"), "psycopg should not be imported directly in the API layer"
    """Perform test api module has no psycopg import."""
