"""Real-ASGI contracts for generic message preview and durable resend."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from pete_e import api
from pete_e.api_errors import get_or_create_correlation_id
from pete_e.api_routes import dependencies, web
from pete_e.application.message_preview import MessagePreviewService
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY


pytestmark = pytest.mark.contract

PREVIEW_PATH = "/console/operations/preview-message"
RESEND_PATH = "/console/operations/resend-message"
SESSION_TOKEN = "message-preview-session"
DEFAULT_REQUEST_ID = "req-message-contract"
INVALID_MESSAGE_DETAIL = "message_type must be summary, trainer, or plan"
_MISSING = object()
_JSON_NULL = object()


def _user(role: str) -> AuthUser:
    return AuthUser(
        id={ROLE_OWNER: 1, ROLE_OPERATOR: 2, ROLE_READ_ONLY: 3}[role],
        username=f"{role}-user",
        email=f"{role}@example.test",
        display_name=role.replace("_", " ").title(),
        roles=(role,),
        is_active=True,
    )


class _UserService:
    def __init__(self, user: AuthUser | None) -> None:
        self.user = user
        self.validations: list[str] = []

    def validate_session_token(self, token: str) -> AuthUser | None:
        self.validations.append(token)
        return self.user if token == SESSION_TOKEN else None


class _BuilderOrchestrator:
    def __init__(self) -> None:
        self.values: dict[str, object] = {
            "summary": "Daily summary preview text",
            "trainer": "Trainer check-in preview text",
            "plan": "Weekly plan preview text",
        }
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.close_calls = 0
        self.weekly_plan_message_builder = self

    def _outcome(self, message_type: str, **kwargs: object) -> object:
        self.calls.append((message_type, kwargs))
        value = self.values[message_type]
        if isinstance(value, Exception):
            raise value
        return value

    def build_daily_summary_message(self, target_date: date | None = None) -> object:
        return self._outcome("summary", target_date=target_date)

    def build_trainer_message(self, message_date: date | None = None) -> object:
        return self._outcome("trainer", message_date=message_date)

    def build_message(
        self,
        *,
        target_date: date | None = None,
        current_date: date | None = None,
    ) -> object:
        return self._outcome(
            "plan",
            target_date=target_date,
            current_date=current_date,
        )

    def close(self) -> None:
        self.close_calls += 1


class _JobService:
    def __init__(self, events: list[tuple[str, Any]]) -> None:
        self.events = events
        self.callback_calls: list[dict[str, Any]] = []
        self.subprocess_calls: list[dict[str, Any]] = []
        self.callback_error: Exception | None = None
        self.subprocess_error: Exception | None = None

    def enqueue_callback(self, **kwargs: Any) -> None:
        self.events.append(("enqueue_callback", kwargs["operation"]))
        self.callback_calls.append(kwargs)
        if self.callback_error is not None:
            raise self.callback_error

    def enqueue_subprocess(self, **kwargs: Any) -> None:
        self.events.append(("enqueue_subprocess", kwargs["operation"]))
        self.subprocess_calls.append(kwargs)
        if self.subprocess_error is not None:
            raise self.subprocess_error


class _Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[tuple[str, Any]] = []
        self.audit_events: list[dict[str, Any]] = []
        self.user_service = _UserService(_user(ROLE_OPERATOR))
        self.job_service = _JobService(self.events)
        self.builder = _BuilderOrchestrator()
        self.job_ids: list[tuple[str, str]] = []
        self.cli_calls: list[tuple[str, ...]] = []
        self.rate_error: Exception | None = None
        self.cli_error: Exception | None = None
        self.audit_hook: Callable[[dict[str, Any]], None] | None = None
        self._route_correlation = web.get_or_create_correlation_id

        monkeypatch.setattr(dependencies, "get_user_service", lambda: self.user_service)
        monkeypatch.setattr(dependencies, "get_job_service", lambda: self.job_service)
        monkeypatch.setattr(dependencies, "prepare_job_context", self._prepare_job)
        monkeypatch.setattr(
            dependencies, "enforce_command_rate_limit", self._rate_limit
        )
        monkeypatch.setattr(dependencies, "audit_command_event", self._audit)
        monkeypatch.setattr(dependencies, "pete_cli_command", self._cli_command)
        monkeypatch.setattr(
            dependencies,
            "get_message_preview_service",
            lambda: MessagePreviewService(
                summary_builder=self.builder,  # type: ignore[arg-type]
                trainer_builder=self.builder,  # type: ignore[arg-type]
                weekly_builder=self.builder,  # type: ignore[arg-type]
            ),
        )
        monkeypatch.setattr(web, "get_or_create_correlation_id", self._correlation)

    def _prepare_job(self, request: Any, operation: str) -> str:
        self.events.append(("prepare_job_context", operation))
        job_id = f"{operation}-job-{len(self.job_ids) + 1}"
        request.state.job_id = job_id
        self.job_ids.append((operation, job_id))
        return job_id

    def _correlation(self, request: Any) -> str:
        request_id = self._route_correlation(request)
        self.events.append(("resolve_request_id", request_id))
        return request_id

    def _rate_limit(self, request: Any, operation: str) -> None:
        self.events.append(("rate_limit", operation))
        if self.rate_error is not None:
            raise self.rate_error

    def _audit(self, request: Any, **event: Any) -> None:
        captured = {
            **event,
            "job_id": getattr(request.state, "job_id", None),
            "request_id": get_or_create_correlation_id(request),
        }
        self.events.append(("audit", captured["outcome"]))
        self.audit_events.append(captured)
        if self.audit_hook is not None:
            self.audit_hook(captured)

    def _cli_command(self, *args: str) -> list[str]:
        self.events.append(("pete_cli_command", args))
        self.cli_calls.append(args)
        if self.cli_error is not None:
            raise self.cli_error
        return ["pete", *args]

    def authorize(self, client: TestClient, role: str = ROLE_OPERATOR) -> str:
        self.user_service.user = _user(role)
        csrf = dependencies.generate_csrf_token(SESSION_TOKEN)
        client.cookies.set(dependencies.session_cookie_name(), SESSION_TOKEN)
        client.cookies.set(dependencies.csrf_cookie_name(), csrf)
        return csrf

    def post(
        self,
        client: TestClient,
        path: str,
        *,
        payload: Any = _MISSING,
        csrf: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        request_headers = {"X-Request-ID": DEFAULT_REQUEST_ID, **(headers or {})}
        if csrf is not None:
            request_headers[dependencies.CSRF_HEADER_NAME] = csrf
        if payload is _MISSING:
            return client.post(path, headers=request_headers)
        if payload is _JSON_NULL:
            request_headers["Content-Type"] = "application/json"
            return client.post(path, content="null", headers=request_headers)
        return client.post(path, json=payload, headers=request_headers)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    return _Harness(monkeypatch)


@pytest.fixture
def client() -> TestClient:
    with TestClient(api.app, raise_server_exceptions=False) as test_client:
        yield test_client


def _error(
    *,
    code: str,
    message: str,
    correlation_id: str = DEFAULT_REQUEST_ID,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "correlation_id": correlation_id,
    }
    if details is not None:
        body["details"] = details
    return {"error": body}


@pytest.mark.parametrize(
    ("message_type", "message", "summary_line"),
    [
        ("summary", "Daily summary preview text", "Daily summary preview generated."),
        (
            "trainer",
            "Trainer check-in preview text",
            "Trainer check-in preview generated.",
        ),
        ("plan", "Weekly plan preview text", "Weekly plan preview generated."),
    ],
)
def test_preview_enqueues_selected_builder_and_exact_storage_contract(
    harness: _Harness,
    client: TestClient,
    message_type: str,
    message: str,
    summary_line: str,
) -> None:
    csrf = harness.authorize(client)

    response = harness.post(
        client,
        PREVIEW_PATH,
        payload={"message_type": message_type},
        csrf=csrf,
        headers={
            "X-Correlation-ID": "corr-message-preview",
            "X-Request-ID": "ignored-request-id",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "queued",
        "command": "message_preview",
        "success": True,
        "summary": "Message preview queued.",
        "message_type": message_type,
        "job_id": "message_preview-job-1",
        "request_id": "corr-message-preview",
        "status_url": "/console/jobs/message_preview-job-1",
        "status_api_url": "/console/jobs/message_preview-job-1/status",
    }
    assert response.headers["X-Correlation-ID"] == "corr-message-preview"
    assert response.headers["X-Request-ID"] == "corr-message-preview"
    assert harness.builder.calls == []
    assert len(harness.job_service.callback_calls) == 1
    call = harness.job_service.callback_calls[0]
    assert call["job_id"] == "message_preview-job-1"
    assert call["operation"] == "message_preview"
    assert call["requester"] == _user(ROLE_OPERATOR)
    assert call["request_id"] == "corr-message-preview"
    assert call["correlation_id"] == "corr-message-preview"
    assert call["request_summary"] == {"message_type": message_type, "send": False}
    assert call["timeout_seconds"] == dependencies.DEFAULT_PROCESS_TIMEOUT_SECONDS
    assert call["auth_scheme"] == "session"

    result = call["callback"]()

    assert result.message_type == message_type
    assert result.message == message
    assert result.success is True
    assert call["result_summary_builder"](result) == summary_line
    assert call["result_output_builder"](result) == message
    assert [selected for selected, _arguments in harness.builder.calls] == [
        message_type
    ]
    assert harness.builder.close_calls == 0
    assert [event[0:2] for event in harness.events[:6]] == [
        ("prepare_job_context", "message_preview"),
        ("resolve_request_id", "corr-message-preview"),
        ("audit", "started"),
        ("rate_limit", "message_preview"),
        ("enqueue_callback", "message_preview"),
        ("audit", "succeeded"),
    ]
    assert [event["outcome"] for event in harness.audit_events] == [
        "started",
        "succeeded",
    ]
    assert harness.audit_events[0]["summary"] == {
        "message_type": message_type,
        "send": False,
    }
    assert harness.audit_events[1]["summary"] == response.json()


@pytest.mark.parametrize("message_type", ["summary", "trainer", "plan"])
def test_resend_enqueues_exact_public_cli_once_and_never_builds_in_process(
    harness: _Harness,
    client: TestClient,
    message_type: str,
) -> None:
    csrf = harness.authorize(client)

    response = harness.post(
        client,
        RESEND_PATH,
        payload={
            "confirmation": "RESEND MESSAGE",
            "message_type": message_type,
        },
        csrf=csrf,
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "queued",
        "command": "message_resend",
        "job_id": "message_resend-job-1",
        "status_url": "/console/jobs/message_resend-job-1",
        "status_api_url": "/console/jobs/message_resend-job-1/status",
        "message_type": message_type,
    }
    assert harness.builder.calls == []
    assert harness.cli_calls == [("message", f"--{message_type}", "--send")]
    assert len(harness.job_service.subprocess_calls) == 1
    call = harness.job_service.subprocess_calls[0]
    assert call == {
        "job_id": "message_resend-job-1",
        "operation": "message_resend",
        "command": ["pete", "message", f"--{message_type}", "--send"],
        "requester": _user(ROLE_OPERATOR),
        "request_id": DEFAULT_REQUEST_ID,
        "correlation_id": DEFAULT_REQUEST_ID,
        "request_summary": {"message_type": message_type},
        "timeout_seconds": dependencies.DEFAULT_PROCESS_TIMEOUT_SECONDS,
        "auth_scheme": "session",
    }
    assert harness.job_service.callback_calls == []
    assert [event["outcome"] for event in harness.audit_events] == [
        "started",
        "succeeded",
    ]


@pytest.mark.parametrize(
    "payload",
    [_MISSING, _JSON_NULL, {}, {"message_type": None}, {"message_type": " plan "}],
)
def test_preview_current_default_and_strip_quirks_select_plan(
    harness: _Harness,
    client: TestClient,
    payload: Any,
) -> None:
    csrf = harness.authorize(client)

    response = harness.post(client, PREVIEW_PATH, payload=payload, csrf=csrf)

    assert response.status_code == 200
    assert response.json()["message_type"] == "plan"
    result = harness.job_service.callback_calls[0]["callback"]()
    assert result.message == "Weekly plan preview text"
    assert harness.builder.calls[0][0] == "plan"


@pytest.mark.parametrize("message_type", [_MISSING, None, " plan "])
def test_resend_omitted_null_and_stripped_type_currently_default_to_plan(
    harness: _Harness,
    client: TestClient,
    message_type: Any,
) -> None:
    csrf = harness.authorize(client)
    payload = {"confirmation": "RESEND MESSAGE"}
    if message_type is not _MISSING:
        payload["message_type"] = message_type

    response = harness.post(client, RESEND_PATH, payload=payload, csrf=csrf)

    assert response.status_code == 200
    assert response.json()["message_type"] == "plan"
    assert harness.cli_calls == [("message", "--plan", "--send")]


@pytest.mark.parametrize(
    "value",
    ["", "   ", "Plan", "SUMMARY", 7, 2.5, True, False, ["plan"], {"type": "plan"}],
)
@pytest.mark.parametrize("path", [PREVIEW_PATH, RESEND_PATH])
def test_invalid_message_values_have_exact_scalar_400_before_job_allocation(
    harness: _Harness,
    client: TestClient,
    value: Any,
    path: str,
) -> None:
    csrf = harness.authorize(client)
    payload = {"message_type": value}
    if path == RESEND_PATH:
        payload["confirmation"] = "RESEND MESSAGE"

    response = harness.post(client, path, payload=payload, csrf=csrf)

    assert response.status_code == 400
    assert response.json() == _error(
        code="bad_request",
        message=INVALID_MESSAGE_DETAIL,
    )
    assert harness.job_ids == []
    assert harness.audit_events == []
    assert harness.job_service.callback_calls == []
    assert harness.job_service.subprocess_calls == []


@pytest.mark.parametrize("payload", [[], "text", 7, 2.5, True, False])
@pytest.mark.parametrize("path", [PREVIEW_PATH, RESEND_PATH])
def test_wrong_json_top_level_uses_real_fastapi_validation_before_authorization(
    harness: _Harness,
    client: TestClient,
    payload: Any,
    path: str,
) -> None:
    response = harness.post(client, path, payload=payload)

    assert response.status_code == 422
    assert response.json() == _error(
        code="validation_error",
        message="Request validation failed",
        details={
            "errors": [
                {
                    "type": "dict_type",
                    "loc": ["body"],
                    "msg": "Invalid value",
                    "input": "[REDACTED]",
                }
            ]
        },
    )
    assert harness.user_service.validations == []
    assert harness.events == []


@pytest.mark.parametrize("path", [PREVIEW_PATH, RESEND_PATH])
def test_malformed_json_uses_real_fastapi_validation_before_authorization(
    harness: _Harness,
    client: TestClient,
    path: str,
) -> None:
    response = client.post(
        path,
        content="{",
        headers={
            "Content-Type": "application/json",
            "X-Request-ID": DEFAULT_REQUEST_ID,
        },
    )

    assert response.status_code == 422
    assert response.json() == _error(
        code="validation_error",
        message="Request validation failed",
        details={
            "errors": [
                {
                    "type": "json_invalid",
                    "loc": ["body", 1],
                    "msg": "Invalid value",
                    "input": "[REDACTED]",
                    "ctx": "[REDACTED]",
                }
            ]
        },
    )
    assert harness.user_service.validations == []
    assert harness.events == []


@pytest.mark.parametrize("path", [PREVIEW_PATH, RESEND_PATH])
@pytest.mark.parametrize(
    ("role", "status_code", "message"),
    [
        (ROLE_READ_ONLY, 403, "Insufficient role"),
        ("anonymous", 401, "Authentication required"),
    ],
)
def test_real_session_rbac_denials_are_audited_before_job(
    harness: _Harness,
    client: TestClient,
    path: str,
    role: str,
    status_code: int,
    message: str,
) -> None:
    csrf = harness.authorize(client, role) if role != "anonymous" else None
    payload = {"message_type": "summary"}
    if path == RESEND_PATH:
        payload["confirmation"] = "RESEND MESSAGE"

    response = harness.post(client, path, payload=payload, csrf=csrf)

    command = "message_preview" if path == PREVIEW_PATH else "message_resend"
    assert response.status_code == status_code
    assert response.json() == _error(
        code="forbidden" if status_code == 403 else "unauthorized",
        message=message,
    )
    assert harness.job_ids == []
    assert harness.audit_events == [
        {
            "command": command,
            "outcome": "authorization_denied",
            "summary": {"status_code": status_code},
            "level": "WARNING",
            "job_id": None,
            "request_id": DEFAULT_REQUEST_ID,
        }
    ]


@pytest.mark.parametrize("path", [PREVIEW_PATH, RESEND_PATH])
@pytest.mark.parametrize(
    ("header_token", "expected_code", "expected_message"),
    [
        (None, "csrf_required", "Missing CSRF token"),
        ("invalid.invalid", "csrf_invalid", "Invalid CSRF token"),
    ],
)
def test_real_csrf_missing_and_bad_token_contract(
    harness: _Harness,
    client: TestClient,
    path: str,
    header_token: str | None,
    expected_code: str,
    expected_message: str,
) -> None:
    harness.authorize(client)
    if header_token is not None:
        client.cookies.set(dependencies.csrf_cookie_name(), header_token)
    payload = {"message_type": "summary"}
    if path == RESEND_PATH:
        payload["confirmation"] = "RESEND MESSAGE"

    response = harness.post(
        client,
        path,
        payload=payload,
        csrf=header_token,
    )

    assert response.status_code == 403
    assert response.json() == _error(code=expected_code, message=expected_message)
    assert harness.audit_events[0]["outcome"] == "authorization_denied"
    assert harness.job_ids == []


@pytest.mark.parametrize("path", [PREVIEW_PATH, RESEND_PATH])
@pytest.mark.parametrize("role", [ROLE_OPERATOR, ROLE_OWNER])
def test_valid_session_and_csrf_accept_operator_and_owner(
    harness: _Harness,
    client: TestClient,
    path: str,
    role: str,
) -> None:
    csrf = harness.authorize(client, role)
    payload = {"message_type": "summary"}
    if path == RESEND_PATH:
        payload["confirmation"] = "RESEND MESSAGE"

    response = harness.post(client, path, payload=payload, csrf=csrf)

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("confirmation", "provided"),
    [(None, False), ("", False), ("resend message", True), ("wrong", True)],
)
def test_resend_requires_exact_confirmation_before_type_and_job(
    harness: _Harness,
    client: TestClient,
    confirmation: str | None,
    provided: bool,
) -> None:
    csrf = harness.authorize(client)
    payload = {"message_type": "not-valid"}
    if confirmation is not None:
        payload["confirmation"] = confirmation

    response = harness.post(client, RESEND_PATH, payload=payload, csrf=csrf)

    assert response.status_code == 400
    assert response.json() == _error(
        code="confirmation_required",
        message="Type RESEND MESSAGE to confirm this command.",
        details={"expected_confirmation": "RESEND MESSAGE"},
    )
    assert harness.job_ids == []
    assert harness.audit_events[0]["outcome"] == "confirmation_failed"
    assert harness.audit_events[0]["summary"] == {
        "expected": "RESEND MESSAGE",
        "provided": provided,
    }


def test_resend_confirmation_is_stripped_but_remains_case_sensitive(
    harness: _Harness,
    client: TestClient,
) -> None:
    csrf = harness.authorize(client)

    response = harness.post(
        client,
        RESEND_PATH,
        payload={"confirmation": "  RESEND MESSAGE \n", "message_type": "plan"},
        csrf=csrf,
    )

    assert response.status_code == 200
    assert harness.cli_calls == [("message", "--plan", "--send")]


@pytest.mark.parametrize(
    ("value", "expected_message", "expected_summary"),
    [
        ("Text", "Text", "Daily summary preview generated."),
        (None, "", "No daily summary message is available."),
        (27, "27", "Daily summary preview generated."),
        (" \n", " \n", "No daily summary message is available."),
    ],
)
def test_preview_callback_value_coercion_blank_summary_and_resource_lifetime(
    harness: _Harness,
    client: TestClient,
    value: object,
    expected_message: str,
    expected_summary: str,
) -> None:
    harness.builder.values["summary"] = value
    csrf = harness.authorize(client)
    response = harness.post(
        client,
        PREVIEW_PATH,
        payload={"message_type": "summary"},
        csrf=csrf,
    )

    assert response.status_code == 200
    call = harness.job_service.callback_calls[0]
    result = call["callback"]()
    assert result.message == expected_message
    assert call["result_summary_builder"](result) == expected_summary
    assert call["result_output_builder"](result) == expected_message
    assert harness.builder.close_calls == 0


def test_preview_builder_exception_occurs_only_when_enqueued_callback_runs(
    harness: _Harness,
    client: TestClient,
) -> None:
    failure = RuntimeError("builder failed")
    harness.builder.values["trainer"] = failure
    csrf = harness.authorize(client)

    response = harness.post(
        client,
        PREVIEW_PATH,
        payload={"message_type": "trainer"},
        csrf=csrf,
    )

    assert response.status_code == 200
    assert harness.builder.calls == []
    with pytest.raises(RuntimeError, match="builder failed") as exc:
        harness.job_service.callback_calls[0]["callback"]()
    assert exc.value is failure
    assert [event["outcome"] for event in harness.audit_events] == [
        "started",
        "succeeded",
    ]


@pytest.mark.parametrize("path", [PREVIEW_PATH, RESEND_PATH])
def test_rate_failure_is_after_started_audit_and_before_enqueue(
    harness: _Harness,
    client: TestClient,
    path: str,
) -> None:
    harness.rate_error = HTTPException(
        status_code=429,
        detail={
            "code": "rate_limited",
            "message": "Slow down",
            "retry_after_seconds": 9,
        },
        headers={"Retry-After": "9"},
    )
    csrf = harness.authorize(client)
    payload = {"message_type": "summary"}
    if path == RESEND_PATH:
        payload["confirmation"] = "RESEND MESSAGE"

    response = harness.post(client, path, payload=payload, csrf=csrf)

    command = "message_preview" if path == PREVIEW_PATH else "message_resend"
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "9"
    assert response.json() == _error(
        code="rate_limited",
        message="Slow down",
        details={"retry_after_seconds": 9},
    )
    assert [event["outcome"] for event in harness.audit_events] == [
        "started",
        "failed",
    ]
    assert harness.audit_events[-1]["summary"] == {
        "status_code": 429,
        "error": str(harness.rate_error.detail),
    }
    assert harness.job_service.callback_calls == []
    assert harness.job_service.subprocess_calls == []
    assert harness.job_ids == [(command, f"{command}-job-1")]


@pytest.mark.parametrize("path", [PREVIEW_PATH, RESEND_PATH])
def test_job_service_failure_is_audited_and_propagates_without_inline_builder(
    harness: _Harness,
    client: TestClient,
    path: str,
) -> None:
    failure = RuntimeError("job store unavailable")
    if path == PREVIEW_PATH:
        harness.job_service.callback_error = failure
    else:
        harness.job_service.subprocess_error = failure
    csrf = harness.authorize(client)
    payload = {"message_type": "summary"}
    if path == RESEND_PATH:
        payload["confirmation"] = "RESEND MESSAGE"

    response = harness.post(client, path, payload=payload, csrf=csrf)

    assert response.status_code == 500
    assert response.json() == _error(
        code="internal_server_error",
        message="Internal server error",
    )
    assert harness.builder.calls == []
    assert [event["outcome"] for event in harness.audit_events] == [
        "started",
        "failed",
    ]
    assert harness.audit_events[-1]["summary"] == {
        "status_code": 500,
        "error": "job store unavailable",
    }


def test_resend_cli_command_construction_failure_is_audited_before_subprocess(
    harness: _Harness,
    client: TestClient,
) -> None:
    harness.cli_error = RuntimeError("CLI path unavailable")
    csrf = harness.authorize(client)

    response = harness.post(
        client,
        RESEND_PATH,
        payload={"confirmation": "RESEND MESSAGE", "message_type": "trainer"},
        csrf=csrf,
    )

    assert response.status_code == 500
    assert harness.cli_calls == [("message", "--trainer", "--send")]
    assert harness.job_service.subprocess_calls == []
    assert [event["outcome"] for event in harness.audit_events] == [
        "started",
        "failed",
    ]


@pytest.mark.parametrize("path", [PREVIEW_PATH, RESEND_PATH])
@pytest.mark.parametrize("failure_point", ["started", "succeeded", "failed"])
def test_audit_exception_timing_before_and_after_enqueue_is_pinned(
    harness: _Harness,
    client: TestClient,
    path: str,
    failure_point: str,
) -> None:
    if failure_point == "failed":
        harness.rate_error = RuntimeError("rate failed")

    def _raise_at(event: dict[str, Any]) -> None:
        if event["outcome"] == failure_point:
            raise RuntimeError(f"audit {failure_point} failed")

    harness.audit_hook = _raise_at
    csrf = harness.authorize(client)
    payload = {"message_type": "summary"}
    if path == RESEND_PATH:
        payload["confirmation"] = "RESEND MESSAGE"

    response = harness.post(client, path, payload=payload, csrf=csrf)

    assert response.status_code == 500
    assert response.json() == _error(
        code="internal_server_error",
        message="Internal server error",
    )
    if failure_point == "started":
        assert harness.job_service.callback_calls == []
        assert harness.job_service.subprocess_calls == []
    elif failure_point == "succeeded":
        enqueued = (
            harness.job_service.callback_calls
            if path == PREVIEW_PATH
            else harness.job_service.subprocess_calls
        )
        assert len(enqueued) == 1
    else:
        assert [event["outcome"] for event in harness.audit_events] == [
            "started",
            "failed",
        ]


@pytest.mark.parametrize("denial", ["authorization", "confirmation"])
def test_pre_job_security_audit_exception_replaces_original_error(
    harness: _Harness,
    client: TestClient,
    denial: str,
) -> None:
    if denial == "authorization":
        path = PREVIEW_PATH
        payload = {"message_type": "summary"}
        csrf = None
        outcome = "authorization_denied"
    else:
        path = RESEND_PATH
        payload = {"message_type": "summary"}
        csrf = harness.authorize(client)
        outcome = "confirmation_failed"

    def _raise_at(event: dict[str, Any]) -> None:
        if event["outcome"] == outcome:
            raise RuntimeError("audit unavailable")

    harness.audit_hook = _raise_at

    response = harness.post(client, path, payload=payload, csrf=csrf)

    assert response.status_code == 500
    assert response.json() == _error(
        code="internal_server_error",
        message="Internal server error",
    )
    assert harness.job_ids == []


def test_missing_or_null_resend_body_fails_confirmation_before_default_type(
    harness: _Harness,
    client: TestClient,
) -> None:
    csrf = harness.authorize(client)

    for payload in (_MISSING, _JSON_NULL):
        response = harness.post(client, RESEND_PATH, payload=payload, csrf=csrf)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "confirmation_required"

    assert harness.job_ids == []


def test_routes_are_mounted_exactly_once_outside_api_v1() -> None:
    routes: list[tuple[str, str]] = []
    for included in api.app.routes:
        original_router = getattr(included, "original_router", None)
        include_context = getattr(included, "include_context", None)
        if original_router is None or include_context is None:
            continue
        prefix = str(include_context.prefix)
        routes.extend(
            (method.upper(), f"{prefix}{route.path}")
            for route in original_router.routes
            for method in getattr(route, "methods", set())
        )

    assert routes.count(("POST", PREVIEW_PATH)) == 1
    assert routes.count(("POST", RESEND_PATH)) == 1
    assert ("POST", f"/api/v1{PREVIEW_PATH}") not in routes
    assert ("POST", f"/api/v1{RESEND_PATH}") not in routes
