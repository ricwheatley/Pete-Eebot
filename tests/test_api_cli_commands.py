import sys
import types

import pytest


# Provide a very small ``fastapi`` stub so the API module can be imported in tests


if "fastapi" not in sys.modules:
    fastapi_module = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str | None = None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class Request:
        def __init__(self, query_params: dict | None = None):
            self.query_params = query_params or {}

    def _identity(value=None, **kwargs):
        return value

    class FastAPI:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    fastapi_module.FastAPI = FastAPI
    fastapi_module.Query = _identity
    fastapi_module.Header = _identity
    fastapi_module.HTTPException = HTTPException
    fastapi_module.Request = Request

    responses_module = types.ModuleType("fastapi.responses")

    class StreamingResponse:  # pragma: no cover - unused in these tests
        def __init__(self, content, media_type=None):
            self.content = content
            self.media_type = media_type

    responses_module.StreamingResponse = StreamingResponse

    sys.modules["fastapi"] = fastapi_module
    sys.modules["fastapi.responses"] = responses_module


from pete_e import api
from pete_e.cli.status import CheckResult
from pete_e.application.sync import SyncResult


@pytest.fixture()
def request_stub() -> api.Request:
    return api.Request({})


@pytest.fixture()
def enable_api_key(monkeypatch):
    monkeypatch.setattr(api.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)


def test_status_endpoint_returns_checks(enable_api_key, request_stub, monkeypatch):
    checks = [
        CheckResult(name="DB", ok=True, detail="5ms"),
        CheckResult(name="Dropbox", ok=False, detail="timeout"),
    ]

    monkeypatch.setattr(api, "run_status_checks", lambda timeout: checks)

    payload = api.status(request=request_stub, x_api_key="test-key", timeout=1.5)

    assert payload["ok"] is False
    assert payload["checks"] == [
        {"name": "DB", "ok": True, "detail": "5ms"},
        {"name": "Dropbox", "ok": False, "detail": "timeout"},
    ]
    assert "Dropbox" in payload["summary"]


def test_status_endpoint_requires_valid_api_key(request_stub, enable_api_key):
    with pytest.raises(api.HTTPException) as exc:
        api.status(request=request_stub, x_api_key=None)

    assert exc.value.status_code == 401


def test_sync_endpoint_returns_sync_result(enable_api_key, request_stub, monkeypatch):
    captured: dict[str, tuple[int, int]] = {}

    def fake_sync(days: int, retries: int):
        captured["args"] = (days, retries)
        return SyncResult(
            success=True,
            attempts=2,
            failed_sources=["Dropbox"],
            source_statuses={"Dropbox": "failed", "Withings": "ok"},
            label="daily",
            undelivered_alerts=["Alert A"],
        )

    monkeypatch.setattr(api, "run_sync_with_retries", fake_sync)

    payload = api.sync(
        request=request_stub,
        x_api_key="test-key",
        days=3,
        retries=1,
    )

    assert captured["args"] == (3, 1)
    assert payload["success"] is True
    assert payload["attempts"] == 2
    assert payload["failed_sources"] == ["Dropbox"]
    assert payload["source_statuses"]["Withings"] == "ok"
    assert "Alert A" in payload["undelivered_alerts"]
    assert "Sync summary" in payload["summary"]


def test_logs_endpoint_returns_tail(enable_api_key, request_stub, tmp_path, monkeypatch):
    log_path = tmp_path / "pete_history.log"
    log_path.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")

    monkeypatch.setattr(type(api.settings), "log_path", property(lambda self: log_path))

    payload = api.logs(request=request_stub, x_api_key="test-key", lines=2)

    assert payload["path"].endswith("pete_history.log")
    assert payload["lines"] == ["line3", "line4"]

