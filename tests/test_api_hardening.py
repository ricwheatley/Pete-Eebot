from __future__ import annotations

import asyncio
from types import SimpleNamespace
import threading
import time

import pytest

from pete_e import api_errors
from pete_e.api_routes import dependencies
from pete_e.application.exceptions import ValidationError
from pete_e.application.concurrency_guard import high_risk_operation_guard


class _Request:
    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}
        self.query_params = {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.state = SimpleNamespace()


def _wait_until_guard_released(timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while high_risk_operation_guard.active_operation is not None:
        if time.monotonic() >= deadline:
            raise AssertionError("guard did not release")
        time.sleep(0.01)


def test_success_responses_receive_correlation_headers_from_middleware() -> None:
    async def _call_next(request):
        assert request.state.correlation_id == "ui-request-123"
        return SimpleNamespace(headers={})

    request = _Request({api_errors.CORRELATION_ID_HEADER: "ui-request-123"})
    response = asyncio.run(api_errors.correlation_id_middleware(request, _call_next))

    assert response.headers[api_errors.CORRELATION_ID_HEADER] == "ui-request-123"
    assert response.headers[api_errors.REQUEST_ID_HEADER] == "ui-request-123"


def test_error_response_schema_includes_generated_correlation_id() -> None:
    request = _Request()

    response = asyncio.run(
        api_errors.http_exception_handler(
            request,
            api_errors.HTTPException(status_code=401, detail="Invalid or missing API key"),
        )
    )

    assert response.status_code == 401
    assert set(response.content.keys()) == {"error"}
    assert response.content["error"]["code"] == "unauthorized"
    assert response.content["error"]["message"] == "Invalid or missing API key"
    assert response.content["error"]["correlation_id"]
    assert response.headers[api_errors.CORRELATION_ID_HEADER] == response.content["error"]["correlation_id"]


def test_error_handlers_share_consistent_schema_for_application_and_http_errors() -> None:
    request = _Request({api_errors.REQUEST_ID_HEADER: "caller-request-7"})

    http_response = asyncio.run(
        api_errors.http_exception_handler(
            request,
            api_errors.HTTPException(
                status_code=409,
                detail={
                    "code": "operation_in_progress",
                    "message": "sync already running",
                    "active_operation": "sync",
                },
            ),
        )
    )
    app_response = asyncio.run(api_errors.application_error_handler(request, ValidationError("bad plan")))

    for response in (http_response, app_response):
        error = response.content["error"]
        assert {"code", "message", "correlation_id"}.issubset(error)
        assert error["correlation_id"] == "caller-request-7"
        assert response.headers[api_errors.CORRELATION_ID_HEADER] == "caller-request-7"

    assert http_response.content["error"]["details"] == {"active_operation": "sync"}
    assert app_response.content["error"]["code"] == "validation_failed"


def test_command_rate_limit_rejects_excess_requests() -> None:
    dependencies.reset_command_rate_limits()
    request = _Request()

    dependencies.enforce_command_rate_limit(request, "sync", max_requests=1, window_seconds=60)
    with pytest.raises(dependencies.HTTPException) as exc:
        dependencies.enforce_command_rate_limit(request, "sync", max_requests=1, window_seconds=60)

    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "rate_limited"
    assert exc.value.detail["operation"] == "sync"


def test_guarded_operation_timeout_returns_504_and_keeps_guard_until_callback_finishes() -> None:
    release_callback = threading.Event()

    def _slow_operation() -> str:
        release_callback.wait(timeout=1)
        return "done"

    try:
        with pytest.raises(dependencies.HTTPException) as exc:
            dependencies.run_guarded_high_risk_operation(
                "sync",
                _slow_operation,
                timeout_seconds=0.01,
            )

        assert exc.value.status_code == 504
        assert exc.value.detail["code"] == "command_timeout"
        assert high_risk_operation_guard.active_operation == "sync"
    finally:
        release_callback.set()
        _wait_until_guard_released()
