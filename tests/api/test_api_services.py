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

    class StreamingResponse:  # pragma: no cover - compatibility with api module
        def __init__(self, content, media_type=None):
            self.content = content
            self.media_type = media_type

    responses_module.StreamingResponse = StreamingResponse

    sys.modules["fastapi"] = fastapi_module
    sys.modules["fastapi.responses"] = responses_module


from pete_e import api


@pytest.fixture()
def request_stub() -> api.Request:
    return api.Request({})


@pytest.fixture()
def enable_api_key(monkeypatch):
    monkeypatch.setattr(api.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)


def test_metrics_overview_uses_service(monkeypatch, enable_api_key, request_stub):
    expected = {"columns": ["col1", "col2"], "rows": [[1, 2], [3, 4]]}
    service = MagicMock()
    service.overview.return_value = expected

    monkeypatch.setattr(api, "get_metrics_service", lambda: service)

    response = api.metrics_overview(request=request_stub, date="2024-01-01", x_api_key="test-key")

    assert response == expected
    service.overview.assert_called_once_with("2024-01-01")


def test_plan_for_day_uses_service(monkeypatch, enable_api_key, request_stub):
    expected = {"columns": ["col"], "rows": [["value"]]}
    service = MagicMock()
    service.for_day.return_value = expected

    monkeypatch.setattr(api, "get_plan_service", lambda: service)

    response = api.plan_for_day(request=request_stub, date="2024-02-02", x_api_key="test-key")

    assert response == expected
    service.for_day.assert_called_once_with("2024-02-02")


def test_plan_for_week_uses_service(monkeypatch, enable_api_key, request_stub):
    expected = {"columns": ["col"], "rows": [["value"]]}
    service = MagicMock()
    service.for_week.return_value = expected

    monkeypatch.setattr(api, "get_plan_service", lambda: service)

    response = api.plan_for_week(request=request_stub, start_date="2024-02-05", x_api_key="test-key")

    assert response == expected
    service.for_week.assert_called_once_with("2024-02-05")


def test_api_module_has_no_psycopg_import():
    assert not hasattr(api, "psycopg"), "psycopg should not be imported directly in the API layer"
