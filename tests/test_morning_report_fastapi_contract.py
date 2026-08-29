"""Real-ASGI contract coverage for the browser morning-report operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from pete_e import api
from pete_e.application.adapter_contracts import (
    NotificationDeliveryResult,
    NotificationMessage,
)
from pete_e.api_errors import get_or_create_correlation_id
from pete_e.api_routes import dependencies, web
from pete_e.application.exceptions import ApplicationError
from pete_e.application.morning_report import MorningReportOperation
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY
from pete_e.domain.prescription_validation import PrescriptionValidationError


pytestmark = pytest.mark.contract

PREVIEW_PATH = "/console/operations/morning-report-preview"
SEND_PATH = "/console/operations/morning-report-send"
SESSION_TOKEN = "morning-report-session"
DEFAULT_REQUEST_ID = "req-morning-contract"


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
        if token != SESSION_TOKEN:
            return None
        return self.user


@dataclass(frozen=True)
class _Result:
    report: str
    target_date: str | None
    sent: bool
    success: bool = True

    def summary_line(self) -> str:
        if not self.report.strip():
            return "No morning report is available yet. Give the sync a minute."
        action = "sent" if self.sent else "generated"
        date_fragment = f" for {self.target_date}" if self.target_date else ""
        return f"Morning report {action}{date_fragment}."


class _JobService:
    def __init__(self, events: list[tuple[str, Any]]) -> None:
        self.events = events
        self.run_calls: list[dict[str, Any]] = []
        self.enqueued = False

    def run_callback(self, **kwargs: Any) -> Any:
        self.events.append(("run_callback", kwargs["operation"]))
        self.run_calls.append(kwargs)
        result = kwargs["callback"]()
        self.events.append(("callback_returned", result))
        return result

    def enqueue_callback(self, **kwargs: Any) -> None:
        self.enqueued = True
        raise AssertionError(f"enqueue_callback must not be used: {kwargs}")

    def enqueue_subprocess(self, **kwargs: Any) -> None:
        self.enqueued = True
        raise AssertionError(f"enqueue_subprocess must not be used: {kwargs}")


class _Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.events: list[tuple[str, Any]] = []
        self.audit_events: list[dict[str, Any]] = []
        self.job_service = _JobService(self.events)
        self.user_service = _UserService(_user(ROLE_OPERATOR))
        self.job_ids: list[tuple[str, str]] = []
        self.outcome: _Result | Exception | Callable[[date | None, bool], Any] = (
            lambda target_date, send: _Result(
                report="Morning report text",
                target_date=target_date.isoformat() if target_date else None,
                sent=send,
            )
        )
        self.audit_hook: Callable[[dict[str, Any]], None] | None = None
        self.rate_error: Exception | None = None
        self.job_error: Exception | None = None
        self._original_parse_optional_date = web._payload_optional_date
        self._original_route_correlation = web.get_or_create_correlation_id

        harness = self

        class _Operation:
            def execute(
                self,
                *,
                target_date: date | None,
                send: bool,
            ) -> Any:
                return harness._generate(target_date=target_date, send=send)

        monkeypatch.setattr(dependencies, "get_user_service", lambda: self.user_service)
        monkeypatch.setattr(dependencies, "get_job_service", lambda: self.job_service)
        monkeypatch.setattr(dependencies, "get_morning_report_operation", _Operation)
        monkeypatch.setattr(
            dependencies, "prepare_job_context", self._prepare_job_context
        )
        monkeypatch.setattr(dependencies, "audit_command_event", self._audit)
        monkeypatch.setattr(
            dependencies, "enforce_command_rate_limit", self._rate_limit
        )
        monkeypatch.setattr(web, "get_or_create_correlation_id", self._correlation)
        monkeypatch.setattr(web, "_payload_optional_date", self._parse_optional_date)

    def _prepare_job_context(self, request: Any, operation: str) -> str:
        self.events.append(("prepare_job_context", operation))
        job_id = f"{operation}-job-{len(self.job_ids) + 1}"
        request.state.job_id = job_id
        self.job_ids.append((operation, job_id))
        return job_id

    def _correlation(self, request: Any) -> str:
        value = self._original_route_correlation(request)
        self.events.append(("resolve_request_id", value))
        return value

    def _parse_optional_date(
        self, payload: dict[str, Any] | None, key: str
    ) -> date | None:
        self.events.append(("parse_optional_date", payload))
        return self._original_parse_optional_date(payload, key)

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

    def _rate_limit(self, request: Any, operation: str) -> None:
        self.events.append(("rate_limit", operation))
        if self.rate_error is not None:
            raise self.rate_error

    def _generate(self, *, target_date: date | None, send: bool) -> Any:
        self.events.append(("application", {"target_date": target_date, "send": send}))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if callable(self.outcome):
            return self.outcome(target_date, send)
        return self.outcome

    def use_original_operation(self, orchestrator: object) -> None:
        class _Channel:
            def send(self, message: NotificationMessage) -> NotificationDeliveryResult:
                delivery = orchestrator.send_telegram_message(message.body)  # type: ignore[attr-defined]
                return NotificationDeliveryResult(
                    channel="telegram",
                    success=bool(delivery),
                )

        operation = MorningReportOperation(
            summary_builder=orchestrator,  # type: ignore[arg-type]
            notification_channel=_Channel(),  # type: ignore[arg-type]
        )
        self.monkeypatch.setattr(
            dependencies,
            "get_morning_report_operation",
            lambda: operation,
        )

    def raise_job_error(self) -> None:
        original = self.job_service.run_callback

        def _raise(**kwargs: Any) -> Any:
            self.events.append(("run_callback", kwargs["operation"]))
            self.job_service.run_calls.append(kwargs)
            if self.job_error is not None:
                raise self.job_error
            return original(**kwargs)

        self.monkeypatch.setattr(self.job_service, "run_callback", _raise)

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
        payload: Any = ...,
        csrf: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        request_headers = {"X-Request-ID": DEFAULT_REQUEST_ID, **(headers or {})}
        if csrf is not None:
            request_headers[dependencies.CSRF_HEADER_NAME] = csrf
        if payload is ...:
            return client.post(path, headers=request_headers)
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


@pytest.mark.parametrize("role", [ROLE_OPERATOR, ROLE_OWNER])
def test_preview_authenticated_operator_and_owner_success(
    harness: _Harness,
    client: TestClient,
    role: str,
) -> None:
    csrf = harness.authorize(client, role)

    response = harness.post(
        client,
        PREVIEW_PATH,
        payload={"target_date": "2026-08-23"},
        csrf=csrf,
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "command": "morning_report_preview",
        "success": True,
        "summary": "Morning report generated for 2026-08-23.",
        "report": "Morning report text",
        "sent": False,
        "target_date": "2026-08-23",
        "job_id": "morning_report_preview-job-1",
        "request_id": DEFAULT_REQUEST_ID,
        "status_url": "/console/jobs/morning_report_preview-job-1",
    }
    assert response.headers["X-Correlation-ID"] == DEFAULT_REQUEST_ID
    assert response.headers["X-Request-ID"] == DEFAULT_REQUEST_ID


@pytest.mark.parametrize("role", [ROLE_OPERATOR, ROLE_OWNER])
def test_confirmed_send_authenticated_operator_and_owner_success(
    harness: _Harness,
    client: TestClient,
    role: str,
) -> None:
    csrf = harness.authorize(client, role)
    harness.outcome = _Result(
        report="Morning report text",
        target_date="2026-08-23",
        sent=True,
    )

    response = harness.post(
        client,
        SEND_PATH,
        payload={
            "confirmation": "SEND MORNING REPORT",
            "target_date": "2026-08-23",
        },
        csrf=csrf,
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "command": "morning_report_send",
        "success": True,
        "summary": "Morning report sent for 2026-08-23.",
        "report": "Morning report text",
        "sent": True,
        "target_date": "2026-08-23",
        "job_id": "morning_report_send-job-1",
        "request_id": DEFAULT_REQUEST_ID,
        "status_url": "/console/jobs/morning_report_send-job-1",
    }


@pytest.mark.parametrize(
    ("role", "status_code", "message"),
    [
        (ROLE_READ_ONLY, 403, "Insufficient role"),
        ("anonymous", 401, "Authentication required"),
    ],
)
def test_preview_denials_are_real_session_rbac_failures_and_are_audited(
    harness: _Harness,
    client: TestClient,
    role: str,
    status_code: int,
    message: str,
) -> None:
    csrf = None
    if role != "anonymous":
        csrf = harness.authorize(client, role)

    response = harness.post(client, PREVIEW_PATH, payload={}, csrf=csrf)

    assert response.status_code == status_code
    assert response.json() == _error(
        code="forbidden" if status_code == 403 else "unauthorized",
        message=message,
    )
    assert harness.job_ids == []
    assert harness.audit_events == [
        {
            "command": "morning_report_preview",
            "outcome": "authorization_denied",
            "summary": {"status_code": status_code},
            "level": "WARNING",
            "job_id": None,
            "request_id": DEFAULT_REQUEST_ID,
        }
    ]


@pytest.mark.parametrize(
    ("header_token", "expected_code", "expected_message"),
    [
        (None, "csrf_required", "Missing CSRF token"),
        ("invalid.invalid", "csrf_invalid", "Invalid CSRF token"),
    ],
)
def test_preview_missing_and_invalid_csrf_use_real_cookie_and_header_validation(
    harness: _Harness,
    client: TestClient,
    header_token: str | None,
    expected_code: str,
    expected_message: str,
) -> None:
    valid_csrf = harness.authorize(client)
    if header_token is not None:
        client.cookies.set(dependencies.csrf_cookie_name(), header_token)

    response = harness.post(
        client,
        PREVIEW_PATH,
        payload={},
        csrf=header_token,
    )

    assert valid_csrf != header_token
    assert response.status_code == 403
    assert response.json() == _error(code=expected_code, message=expected_message)
    assert harness.audit_events[0]["outcome"] == "authorization_denied"
    assert harness.job_ids == []


@pytest.mark.parametrize(
    ("confirmation", "provided"),
    [(None, False), ("send morning report", True), ("SEND MORNING REPORT ", False)],
)
def test_send_requires_exact_confirmation_before_job_allocation(
    harness: _Harness,
    client: TestClient,
    confirmation: str | None,
    provided: bool,
) -> None:
    csrf = harness.authorize(client)
    payload = {} if confirmation is None else {"confirmation": confirmation}

    response = harness.post(client, SEND_PATH, payload=payload, csrf=csrf)

    if confirmation == "SEND MORNING REPORT ":
        assert response.status_code == 200
        assert harness.job_ids == [("morning_report_send", "morning_report_send-job-1")]
        return
    assert response.status_code == 400
    assert response.json() == _error(
        code="confirmation_required",
        message="Type SEND MORNING REPORT to confirm this command.",
        details={"expected_confirmation": "SEND MORNING REPORT"},
    )
    assert harness.job_ids == []
    assert harness.audit_events == [
        {
            "command": "morning_report_send",
            "outcome": "confirmation_failed",
            "summary": {
                "expected": "SEND MORNING REPORT",
                "provided": provided,
            },
            "level": "WARNING",
            "job_id": None,
            "request_id": DEFAULT_REQUEST_ID,
        }
    ]


@pytest.mark.parametrize(
    ("payload", "expected_date"),
    [
        (..., None),
        (None, None),
        ({}, None),
        ({"target_date": "2026-08-23"}, date(2026, 8, 23)),
        ({"target_date": None}, None),
        ({"target_date": ""}, None),
        ({"target_date": []}, None),
        ({"target_date": {}}, None),
        ({"target_date": False}, None),
        ({"target_date": 20260823}, date(2026, 8, 23)),
    ],
)
def test_preview_payload_success_characterization(
    harness: _Harness,
    client: TestClient,
    payload: Any,
    expected_date: date | None,
) -> None:
    csrf = harness.authorize(client)

    response = harness.post(client, PREVIEW_PATH, payload=payload, csrf=csrf)

    assert response.status_code == 200
    expected_iso = expected_date.isoformat() if expected_date else None
    expected_summary = (
        f"Morning report generated for {expected_iso}."
        if expected_iso
        else "Morning report generated."
    )
    assert response.json() == {
        "status": "completed",
        "command": "morning_report_preview",
        "success": True,
        "summary": expected_summary,
        "report": "Morning report text",
        "sent": False,
        "target_date": expected_iso,
        "job_id": "morning_report_preview-job-1",
        "request_id": DEFAULT_REQUEST_ID,
        "status_url": "/console/jobs/morning_report_preview-job-1",
    }
    application_event = next(
        value for name, value in harness.events if name == "application"
    )
    assert application_event == {"target_date": expected_date, "send": False}


@pytest.mark.parametrize(
    "payload",
    [
        {"target_date": "23-08-2026"},
        {"target_date": "2026-02-30"},
        {"target_date": 2026.5},
        {"target_date": ["2026-08-23"]},
        {"target_date": {"date": "2026-08-23"}},
    ],
)
def test_preview_malformed_and_wrong_typed_dates_have_exact_route_error(
    harness: _Harness,
    client: TestClient,
    payload: dict[str, Any],
) -> None:
    csrf = harness.authorize(client)

    response = harness.post(client, PREVIEW_PATH, payload=payload, csrf=csrf)

    assert response.status_code == 400
    assert response.json() == _error(
        code="invalid_date",
        message="target_date must use YYYY-MM-DD",
        details={
            "field": "target_date",
            "job_id": "morning_report_preview-job-1",
            "request_id": DEFAULT_REQUEST_ID,
        },
    )
    assert [event[0:2] for event in harness.events] == [
        ("prepare_job_context", "morning_report_preview"),
        ("resolve_request_id", DEFAULT_REQUEST_ID),
        ("parse_optional_date", payload),
        ("audit", "failed"),
    ]


@pytest.mark.parametrize("payload", [[], "text", 7, 2.5, True, False])
def test_preview_wrong_json_top_level_uses_exact_fastapi_validation_contract(
    harness: _Harness,
    client: TestClient,
    payload: Any,
) -> None:
    csrf = harness.authorize(client)

    response = harness.post(client, PREVIEW_PATH, payload=payload, csrf=csrf)

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


@pytest.mark.parametrize(
    ("value", "expected_report"),
    [("Report", "Report"), ("  \n", "  \n"), (None, ""), (27, "27")],
)
def test_original_preview_builder_value_conversion_through_real_route(
    harness: _Harness,
    client: TestClient,
    value: object,
    expected_report: str,
) -> None:
    close_calls: list[bool] = []

    class _Orchestrator:
        def build_daily_summary_message(
            self, target_date: date | None = None
        ) -> object:
            assert target_date == date(2026, 8, 23)
            return value

        def send_telegram_message(self, message: str) -> bool:
            raise AssertionError(f"preview must not send: {message}")

        def close(self) -> None:
            close_calls.append(True)

    harness.use_original_operation(_Orchestrator())
    csrf = harness.authorize(client)

    response = harness.post(
        client,
        PREVIEW_PATH,
        payload={"target_date": "2026-08-23"},
        csrf=csrf,
    )

    assert response.status_code == 200
    assert response.json()["report"] == expected_report
    assert response.json()["sent"] is False
    assert close_calls == []


@pytest.mark.parametrize(
    ("report", "delivery", "expected_sent"),
    [("Send this", True, True), (" \n", True, False)],
)
def test_original_send_blank_decision_and_success_through_real_route(
    harness: _Harness,
    client: TestClient,
    report: str,
    delivery: bool,
    expected_sent: bool,
) -> None:
    sent: list[str] = []
    close_calls: list[bool] = []

    class _Orchestrator:
        def build_daily_summary_message(self, target_date: date | None = None) -> str:
            return report

        def send_telegram_message(self, message: str) -> bool:
            sent.append(message)
            return delivery

        def close(self) -> None:
            close_calls.append(True)

    harness.use_original_operation(_Orchestrator())
    csrf = harness.authorize(client)

    response = harness.post(
        client,
        SEND_PATH,
        payload={"confirmation": "SEND MORNING REPORT"},
        csrf=csrf,
    )

    assert response.status_code == 200
    assert response.json()["report"] == report
    assert response.json()["sent"] is expected_sent
    assert sent == ([report] if expected_sent else [])
    assert close_calls == []


@pytest.mark.parametrize(
    ("delivery", "raised", "expected_message"),
    [
        (False, None, "Telegram send for morning report failed."),
        (True, OSError("network down"), "network down"),
    ],
)
def test_original_send_false_and_transport_exception_mapping(
    harness: _Harness,
    client: TestClient,
    delivery: bool,
    raised: Exception | None,
    expected_message: str,
) -> None:
    class _Orchestrator:
        def build_daily_summary_message(self, target_date: date | None = None) -> str:
            return "Send this"

        def send_telegram_message(self, message: str) -> bool:
            if raised is not None:
                raise raised
            return delivery

    harness.use_original_operation(_Orchestrator())
    csrf = harness.authorize(client)

    response = harness.post(
        client,
        SEND_PATH,
        payload={"confirmation": "SEND MORNING REPORT"},
        csrf=csrf,
    )

    assert response.status_code == 500
    assert response.json() == _error(
        code="morning_report_send_failed",
        message=expected_message,
        details={
            "job_id": "morning_report_send-job-1",
            "request_id": DEFAULT_REQUEST_ID,
        },
    )


@pytest.mark.parametrize(
    ("exc", "expected_message"),
    [
        (ApplicationError("application failed"), "application failed"),
        (
            PrescriptionValidationError(["domain failed"]),
            "Invalid training prescription: domain failed",
        ),
        (RuntimeError("general failed"), "general failed"),
        (RuntimeError(), "Morning report preview failed."),
    ],
)
def test_callback_exception_families_preserve_non_http_mapping(
    harness: _Harness,
    client: TestClient,
    exc: Exception,
    expected_message: str,
) -> None:
    harness.outcome = exc
    csrf = harness.authorize(client)

    response = harness.post(client, PREVIEW_PATH, payload={}, csrf=csrf)

    assert response.status_code == 500
    assert response.json() == _error(
        code="morning_report_preview_failed",
        message=expected_message,
        details={
            "job_id": "morning_report_preview-job-1",
            "request_id": DEFAULT_REQUEST_ID,
        },
    )


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        (
            {"code": "operation_busy", "message": "Already running", "active": "sync"},
            _error(
                code="operation_busy",
                message="Already running",
                details={
                    "active": "sync",
                    "job_id": "morning_report_preview-job-1",
                    "request_id": DEFAULT_REQUEST_ID,
                },
            ),
        ),
        (
            "Already running",
            _error(
                code="morning_report_preview_failed",
                message="Already running",
                details={
                    "job_id": "morning_report_preview-job-1",
                    "request_id": DEFAULT_REQUEST_ID,
                },
            ),
        ),
        (
            "",
            _error(
                code="morning_report_preview_failed",
                message="Morning report preview failed.",
                details={
                    "job_id": "morning_report_preview-job-1",
                    "request_id": DEFAULT_REQUEST_ID,
                },
            ),
        ),
    ],
)
def test_http_exception_crossing_callback_boundary_preserves_status_and_detail_shape(
    harness: _Harness,
    client: TestClient,
    detail: Any,
    expected: dict[str, Any],
) -> None:
    harness.outcome = HTTPException(status_code=409, detail=detail)
    csrf = harness.authorize(client)

    response = harness.post(client, PREVIEW_PATH, payload={}, csrf=csrf)

    assert response.status_code == 409
    assert response.json() == expected


def test_rate_limit_failure_occurs_after_started_audit_before_job_and_loses_original_headers(
    harness: _Harness,
    client: TestClient,
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

    response = harness.post(client, PREVIEW_PATH, payload={}, csrf=csrf)

    assert response.status_code == 429
    assert response.json() == _error(
        code="rate_limited",
        message="Slow down",
        details={
            "retry_after_seconds": 9,
            "job_id": "morning_report_preview-job-1",
            "request_id": DEFAULT_REQUEST_ID,
        },
    )
    assert "Retry-After" not in response.headers
    assert [event[0:2] for event in harness.events] == [
        ("prepare_job_context", "morning_report_preview"),
        ("resolve_request_id", DEFAULT_REQUEST_ID),
        ("parse_optional_date", {}),
        ("audit", "started"),
        ("rate_limit", "morning_report_preview"),
        ("audit", "failed"),
    ]


def test_job_service_failure_is_audited_and_mapped_without_application_call(
    harness: _Harness,
    client: TestClient,
) -> None:
    harness.job_error = RuntimeError("job store unavailable")
    harness.raise_job_error()
    csrf = harness.authorize(client)

    response = harness.post(client, PREVIEW_PATH, payload={}, csrf=csrf)

    assert response.status_code == 500
    assert response.json() == _error(
        code="morning_report_preview_failed",
        message="job store unavailable",
        details={
            "job_id": "morning_report_preview-job-1",
            "request_id": DEFAULT_REQUEST_ID,
        },
    )
    assert not any(name == "application" for name, _value in harness.events)
    assert [event["outcome"] for event in harness.audit_events] == ["started", "failed"]


def test_callback_arguments_timing_audits_ids_and_response_are_exact(
    harness: _Harness,
    client: TestClient,
) -> None:
    harness.outcome = lambda target, send: _Result(
        report="Dated report",
        target_date=target.isoformat() if target else None,
        sent=send,
    )
    csrf = harness.authorize(client)

    response = harness.post(
        client,
        SEND_PATH,
        payload={
            "confirmation": "SEND MORNING REPORT",
            "target_date": "2026-08-23",
        },
        csrf=csrf,
        headers={
            "X-Correlation-ID": "corr-inbound",
            "X-Request-ID": "request-inbound",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "corr-inbound"
    assert response.headers["X-Request-ID"] == "corr-inbound"
    call = harness.job_service.run_calls[0]
    assert call["job_id"] == "morning_report_send-job-1"
    assert call["operation"] == "morning_report_send"
    assert call["requester"] == _user(ROLE_OPERATOR)
    assert call["request_id"] == "corr-inbound"
    assert call["correlation_id"] == "corr-inbound"
    assert call["request_summary"] == {"target_date": "2026-08-23", "send": True}
    assert call["timeout_seconds"] == dependencies.DEFAULT_PROCESS_TIMEOUT_SECONDS
    assert call["auth_scheme"] == "session"
    assert call["result_summary_builder"](response_result := call["callback"]()) == (
        response_result.summary_line()
    )
    assert harness.job_service.enqueued is False
    assert [event[0:2] for event in harness.events[:7]] == [
        ("prepare_job_context", "morning_report_send"),
        ("resolve_request_id", "corr-inbound"),
        (
            "parse_optional_date",
            {"confirmation": "SEND MORNING REPORT", "target_date": "2026-08-23"},
        ),
        ("audit", "started"),
        ("rate_limit", "morning_report_send"),
        ("run_callback", "morning_report_send"),
        (
            "application",
            {"target_date": date(2026, 8, 23), "send": True},
        ),
    ]
    assert [event["outcome"] for event in harness.audit_events] == [
        "started",
        "succeeded",
    ]
    assert harness.audit_events[0]["summary"] == {
        "target_date": "2026-08-23",
        "send": True,
    }
    assert harness.audit_events[1]["summary"] == response.json()


@pytest.mark.parametrize(
    ("failure_point", "expected_events", "expected_message"),
    [
        ("started", ["started", "failed"], "audit started failed"),
        ("succeeded", ["started", "succeeded"], "Internal server error"),
        ("failed", ["started", "failed"], "Internal server error"),
    ],
)
def test_audit_failure_quirks_before_and_after_callback_are_pinned(
    harness: _Harness,
    client: TestClient,
    failure_point: str,
    expected_events: list[str],
    expected_message: str,
) -> None:
    if failure_point == "failed":
        harness.outcome = RuntimeError("builder failed")

    def _audit_hook(event: dict[str, Any]) -> None:
        if event["outcome"] == failure_point:
            raise RuntimeError(f"audit {failure_point} failed")

    harness.audit_hook = _audit_hook
    csrf = harness.authorize(client)

    response = harness.post(client, PREVIEW_PATH, payload={}, csrf=csrf)

    assert response.status_code == 500
    assert [event["outcome"] for event in harness.audit_events] == expected_events
    if failure_point == "started":
        assert response.json() == _error(
            code="morning_report_preview_failed",
            message=expected_message,
            details={
                "job_id": "morning_report_preview-job-1",
                "request_id": DEFAULT_REQUEST_ID,
            },
        )
        assert harness.job_service.run_calls == []
    else:
        assert response.json() == _error(
            code="internal_server_error",
            message=expected_message,
        )


@pytest.mark.parametrize("denial", ["authorization", "confirmation"])
def test_pre_job_security_audit_failure_replaces_original_error(
    harness: _Harness,
    client: TestClient,
    denial: str,
) -> None:
    if denial == "authorization":
        payload: dict[str, Any] = {}
        path = PREVIEW_PATH
        csrf = None
        failed_outcome = "authorization_denied"
    else:
        payload = {}
        path = SEND_PATH
        csrf = harness.authorize(client)
        failed_outcome = "confirmation_failed"

    def _audit_hook(event: dict[str, Any]) -> None:
        if event["outcome"] == failed_outcome:
            raise RuntimeError("audit unavailable")

    harness.audit_hook = _audit_hook

    response = harness.post(client, path, payload=payload, csrf=csrf)

    assert response.status_code == 500
    assert response.json() == _error(
        code="internal_server_error",
        message="Internal server error",
    )
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
    assert routes.count(("POST", SEND_PATH)) == 1
    assert ("POST", f"/api/v1{PREVIEW_PATH}") not in routes
    assert ("POST", f"/api/v1{SEND_PATH}") not in routes
