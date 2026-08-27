from __future__ import annotations

from dataclasses import dataclass, field
import datetime as datetime_module
import hashlib
import hmac
import json
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from pete_e import api
from pete_e.api_routes import logs_webhooks
from pete_e.infrastructure.edge_security_repository import DeliveryClaim


pytestmark = pytest.mark.contract

_SECRET = b"github-webhook-contract-secret"
_REPOSITORY_ID = 1044067254
_COMMIT_SHA = "a" * 40
_CORRELATION_ID = "github-contract-correlation"
_NOW = datetime_module.datetime(
    2026, 8, 23, 10, 11, 12, 345678, tzinfo=datetime_module.timezone.utc
)


class CollaboratorFailure(RuntimeError):
    pass


class _FrozenDateTime(datetime_module.datetime):
    @classmethod
    def now(cls, tz: datetime_module.tzinfo | None = None) -> datetime_module.datetime:
        return _NOW if tz is not None else _NOW.replace(tzinfo=None)


@dataclass
class RecordingLedger:
    events: list[tuple[Any, ...]]
    claim: DeliveryClaim = field(
        default_factory=lambda: DeliveryClaim(
            True, "delivery-1", "deploy-contract-job", "accepted"
        )
    )
    claim_error: Exception | None = None
    mark_errors: dict[str, Exception] = field(default_factory=dict)

    def claim_github_delivery(self, **kwargs: object) -> DeliveryClaim:
        self.events.append(("claim", kwargs))
        if self.claim_error is not None:
            raise self.claim_error
        return self.claim

    def mark_github_delivery(
        self,
        delivery_id: str,
        *,
        status: str,
        failure_reason: str | None = None,
    ) -> None:
        self.events.append(("mark", delivery_id, status, failure_reason))
        error = self.mark_errors.get(status)
        if error is not None:
            raise error


@dataclass
class WebhookBoundary:
    events: list[tuple[Any, ...]]
    ledger: RecordingLedger
    rate_error: Exception | None = None
    dispatch_error: Exception | None = None
    audit_errors: dict[str, Exception] = field(default_factory=dict)
    correlation_error: Exception | None = None
    command_error: Exception | None = None
    clock_error: Exception | None = None


def _valid_payload() -> dict[str, object]:
    return {
        "repository": {"id": _REPOSITORY_ID},
        "ref": "refs/heads/main",
        "after": _COMMIT_SHA,
        "deleted": False,
    }


def _signed_headers(
    body: bytes,
    *,
    event: str = "push",
    delivery_id: str = "delivery-1",
) -> dict[str, str]:
    digest = hmac.new(_SECRET, body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Correlation-ID": _CORRELATION_ID,
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": f"sha256={digest}",
    }


def _request_parts(
    payload: dict[str, object] | None = None,
    *,
    event: str = "push",
    delivery_id: str = "delivery-1",
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload or _valid_payload(), separators=(",", ":")).encode()
    return body, _signed_headers(body, event=event, delivery_id=delivery_id)


def _error_payload(code: str, message: str) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "correlation_id": _CORRELATION_ID,
        }
    }


@pytest.fixture()
def webhook_boundary(monkeypatch: pytest.MonkeyPatch) -> WebhookBoundary:
    events: list[tuple[Any, ...]] = []
    boundary = WebhookBoundary(events=events, ledger=RecordingLedger(events))

    def configured_secret() -> bytes:
        events.append(("secret",))
        return _SECRET

    def prepare(request: object, operation: str) -> str:
        state = getattr(request, "state", None)
        events.append(("prepare", operation, getattr(state, "auth_scheme", None)))
        return "deploy-contract-job"

    def rate(request: object, operation: str) -> None:
        state = getattr(request, "state", None)
        events.append(("rate", operation, getattr(state, "auth_scheme", None)))
        if boundary.rate_error is not None:
            raise boundary.rate_error

    def audit(
        request: object,
        *,
        command: str,
        outcome: str,
        summary: dict[str, object],
        level: str = "INFO",
    ) -> None:
        events.append(("audit", command, outcome, summary, level))
        error = boundary.audit_errors.get(outcome)
        if error is not None:
            raise error

    def correlation(_request: object) -> str:
        events.append(("correlation",))
        if boundary.correlation_error is not None:
            raise boundary.correlation_error
        return _CORRELATION_ID

    def command(job_id: str) -> list[str]:
        events.append(("command", job_id))
        if boundary.command_error is not None:
            raise boundary.command_error
        return ["dispatch", job_id]

    class JobService:
        def dispatch_external(self, **kwargs: object) -> None:
            events.append(("dispatch", kwargs))
            if boundary.dispatch_error is not None:
                raise boundary.dispatch_error

    def job_service() -> JobService:
        events.append(("job_service",))
        return JobService()

    class ClockDateTime(_FrozenDateTime):
        @classmethod
        def now(
            cls, tz: datetime_module.tzinfo | None = None
        ) -> datetime_module.datetime:
            events.append(("clock",))
            if boundary.clock_error is not None:
                raise boundary.clock_error
            return super().now(tz)

    monkeypatch.setattr(logs_webhooks, "configured_webhook_secret", configured_secret)
    monkeypatch.setattr(
        logs_webhooks.settings, "PETEEEBOT_GITHUB_REPOSITORY_ID", _REPOSITORY_ID
    )
    monkeypatch.setattr(
        logs_webhooks.settings, "PETEEEBOT_GITHUB_DEPLOY_REF", "refs/heads/main"
    )
    monkeypatch.setattr(
        logs_webhooks.settings, "PETEEEBOT_WEBHOOK_MAX_BODY_BYTES", 4096
    )
    monkeypatch.setattr(
        logs_webhooks.settings, "PETEEEBOT_DEPLOY_DISPATCH_TIMEOUT_SECONDS", 37
    )
    monkeypatch.setattr(
        logs_webhooks, "get_github_delivery_ledger", lambda: boundary.ledger
    )
    monkeypatch.setattr(logs_webhooks, "prepare_job_context", prepare)
    monkeypatch.setattr(logs_webhooks, "enforce_command_rate_limit", rate)
    monkeypatch.setattr(logs_webhooks, "audit_command_event", audit)
    monkeypatch.setattr(logs_webhooks, "get_or_create_correlation_id", correlation)
    monkeypatch.setattr(logs_webhooks, "configured_deploy_dispatch_command", command)
    monkeypatch.setattr(logs_webhooks, "get_job_service", job_service)
    monkeypatch.setattr(
        logs_webhooks,
        "datetime",
        SimpleNamespace(datetime=ClockDateTime, timezone=datetime_module.timezone),
    )
    return boundary


def _post(
    body: bytes,
    headers: dict[str, str],
    *,
    raise_server_exceptions: bool = True,
):
    with TestClient(api.app, raise_server_exceptions=raise_server_exceptions) as client:
        return client.post("/api/v1/webhook", content=body, headers=headers)


@pytest.mark.parametrize(
    ("signature", "message"),
    [
        (None, "Missing signature"),
        ("sha256", "Bad signature format"),
        ("sha256=one=two", "Bad signature format"),
        ("sha1=digest", "Unsupported signature type"),
        ("=digest", "Unsupported signature type"),
    ],
)
def test_signature_shape_rejections_precede_body_and_collaborators(
    webhook_boundary: WebhookBoundary,
    signature: str | None,
    message: str,
) -> None:
    body, headers = _request_parts()
    if signature is None:
        headers.pop("X-Hub-Signature-256")
    else:
        headers["X-Hub-Signature-256"] = signature

    response = _post(body, headers)

    assert response.status_code == 403
    assert response.json() == _error_payload("forbidden", message)
    assert response.headers["X-Correlation-ID"] == _CORRELATION_ID
    assert response.headers["X-Request-ID"] == _CORRELATION_ID
    assert webhook_boundary.events == []


def test_invalid_signature_does_not_decode_filter_claim_or_dispatch(
    webhook_boundary: WebhookBoundary,
) -> None:
    body = b"\xffnot-json"
    headers = _signed_headers(body)
    headers["X-Hub-Signature-256"] = "sha256=" + "f" * 64

    response = _post(body, headers)

    assert response.status_code == 403
    assert response.json() == _error_payload("forbidden", "Invalid signature")
    assert webhook_boundary.events == [("secret",)]


def test_auth_scheme_is_set_only_after_valid_hmac(
    webhook_boundary: WebhookBoundary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_schemes: list[object] = []
    original_parse_candidate = logs_webhooks._parse_candidate

    def observe_authenticated_state(request: object, body: bytes):
        observed_schemes.append(
            getattr(getattr(request, "state", None), "auth_scheme", None)
        )
        return original_parse_candidate(request, body)

    monkeypatch.setattr(logs_webhooks, "_parse_candidate", observe_authenticated_state)
    invalid_body = b"not-json"
    invalid_headers = _signed_headers(invalid_body)
    invalid_headers["X-Hub-Signature-256"] = "sha256=" + "f" * 64

    invalid_signature = _post(invalid_body, invalid_headers)
    valid_signature = _post(invalid_body, _signed_headers(invalid_body))

    assert invalid_signature.status_code == 403
    assert valid_signature.status_code == 400
    assert observed_schemes == ["github_webhook_hmac"]


def test_missing_secret_is_reported_only_after_the_bounded_body(
    webhook_boundary: WebhookBoundary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_secret() -> bytes:
        webhook_boundary.events.append(("secret",))
        raise HTTPException(
            status_code=503,
            detail="GITHUB_WEBHOOK_SECRET is not configured",
        )

    monkeypatch.setattr(logs_webhooks, "configured_webhook_secret", missing_secret)
    body, headers = _request_parts()

    response = _post(body, headers)

    assert response.status_code == 503
    assert response.json() == _error_payload(
        "service_unavailable", "GITHUB_WEBHOOK_SECRET is not configured"
    )
    assert webhook_boundary.events == [("secret",)]


@pytest.mark.parametrize(
    ("raw_length", "maximum", "status_code", "message"),
    [
        ("invalid", 4096, 400, "Invalid Content-Length"),
        ("-1", 4096, 400, "Invalid Content-Length"),
        ("101", 100, 413, "Webhook body too large"),
    ],
)
def test_invalid_content_length_is_rejected_before_secret_access(
    webhook_boundary: WebhookBoundary,
    monkeypatch: pytest.MonkeyPatch,
    raw_length: str,
    maximum: int,
    status_code: int,
    message: str,
) -> None:
    body, headers = _request_parts()
    headers["Content-Length"] = raw_length
    monkeypatch.setattr(
        logs_webhooks.settings, "PETEEEBOT_WEBHOOK_MAX_BODY_BYTES", maximum
    )

    response = _post(body, headers)

    code = "bad_request" if status_code == 400 else "http_error"
    assert response.status_code == status_code
    assert response.json() == _error_payload(code, message)
    assert webhook_boundary.events == []


@pytest.mark.parametrize("use_explicit_length", [False, True])
def test_body_at_limit_is_read_before_json_rejection(
    webhook_boundary: WebhookBoundary,
    monkeypatch: pytest.MonkeyPatch,
    use_explicit_length: bool,
) -> None:
    body = b" " * 64
    headers = _signed_headers(body)
    monkeypatch.setattr(
        logs_webhooks.settings, "PETEEEBOT_WEBHOOK_MAX_BODY_BYTES", len(body)
    )
    if use_explicit_length:
        headers["Content-Length"] = str(len(body))

    if use_explicit_length:
        response = _post(body, headers)
    else:
        with TestClient(api.app) as client:
            response = client.post(
                "/api/v1/webhook",
                content=iter((body[:17], body[17:])),
                headers=headers,
            )

    assert response.status_code == 400
    assert response.json() == _error_payload("bad_request", "Invalid JSON payload")
    assert webhook_boundary.events == [("secret",)]


def test_chunked_body_over_limit_is_rejected_before_secret_access(
    webhook_boundary: WebhookBoundary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"x" * 65
    headers = _signed_headers(body)
    monkeypatch.setattr(logs_webhooks.settings, "PETEEEBOT_WEBHOOK_MAX_BODY_BYTES", 64)

    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/webhook",
            content=iter((body[:32], body[32:])),
            headers=headers,
        )

    assert response.status_code == 413
    assert response.json() == _error_payload("http_error", "Webhook body too large")
    assert webhook_boundary.events == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"", "Invalid JSON payload"),
        (b"\xff", "Invalid JSON payload"),
        (b"{", "Invalid JSON payload"),
        (b"[]", "JSON payload must be an object"),
        (b'"string"', "JSON payload must be an object"),
        (b"null", "JSON payload must be an object"),
    ],
)
def test_signed_body_decode_and_shape_rejections_are_exact(
    webhook_boundary: WebhookBoundary,
    body: bytes,
    message: str,
) -> None:
    response = _post(body, _signed_headers(body))

    assert response.status_code == 400
    assert response.json() == _error_payload("bad_request", message)
    assert webhook_boundary.events == [("secret",)]


@pytest.mark.parametrize(
    ("delivery_id", "accepted"),
    [
        ("a", True),
        ("a" * 128, True),
        ("", False),
        ("bad_value", False),
        ("a" * 129, False),
    ],
)
def test_delivery_id_boundaries(
    webhook_boundary: WebhookBoundary,
    delivery_id: str,
    accepted: bool,
) -> None:
    body, headers = _request_parts(delivery_id=delivery_id)
    if not delivery_id:
        headers.pop("X-GitHub-Delivery")

    response = _post(body, headers)

    if accepted:
        assert response.status_code == 200
        claim = next(event for event in webhook_boundary.events if event[0] == "claim")
        assert claim[1]["delivery_id"] == delivery_id
    else:
        assert response.status_code == 422
        assert response.json() == _error_payload(
            "invalid_webhook", "Missing or invalid X-GitHub-Delivery"
        )
        assert webhook_boundary.events == [("secret",)]


@pytest.mark.parametrize(
    ("repository_id", "deploy_ref", "status_code", "message"),
    [
        (
            None,
            "refs/heads/main",
            503,
            "PETEEEBOT_GITHUB_REPOSITORY_ID is not configured",
        ),
        (0, "refs/heads/main", 503, "PETEEEBOT_GITHUB_REPOSITORY_ID is not configured"),
        (
            _REPOSITORY_ID,
            "",
            503,
            "PETEEEBOT_GITHUB_DEPLOY_REF must be refs/heads/main",
        ),
        (
            _REPOSITORY_ID,
            "refs/heads/release",
            503,
            "PETEEEBOT_GITHUB_DEPLOY_REF must be refs/heads/main",
        ),
    ],
)
def test_configuration_rejections_follow_signed_json_validation(
    webhook_boundary: WebhookBoundary,
    monkeypatch: pytest.MonkeyPatch,
    repository_id: int | None,
    deploy_ref: str,
    status_code: int,
    message: str,
) -> None:
    monkeypatch.setattr(
        logs_webhooks.settings, "PETEEEBOT_GITHUB_REPOSITORY_ID", repository_id
    )
    monkeypatch.setattr(
        logs_webhooks.settings, "PETEEEBOT_GITHUB_DEPLOY_REF", deploy_ref
    )
    body, headers = _request_parts()

    response = _post(body, headers)

    assert response.status_code == status_code
    assert response.json() == _error_payload("service_unavailable", message)
    assert webhook_boundary.events == [("secret",)]


def test_configured_ref_whitespace_is_stripped_before_exact_main_comparison(
    webhook_boundary: WebhookBoundary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        logs_webhooks.settings,
        "PETEEEBOT_GITHUB_DEPLOY_REF",
        "  refs/heads/main  ",
    )
    body, headers = _request_parts()

    response = _post(body, headers)

    assert response.status_code == 200
    claim = next(event for event in webhook_boundary.events if event[0] == "claim")
    assert claim[1]["ref_name"] == "refs/heads/main"


def test_non_numeric_repository_configuration_propagates_value_error(
    webhook_boundary: WebhookBoundary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        logs_webhooks.settings, "PETEEEBOT_GITHUB_REPOSITORY_ID", "not-an-integer"
    )
    body, headers = _request_parts()

    with pytest.raises(ValueError, match="invalid literal"):
        _post(body, headers)

    serialized = _post(body, headers, raise_server_exceptions=False)
    assert serialized.status_code == 500
    assert serialized.json() == _error_payload(
        "internal_server_error", "Internal server error"
    )
    assert webhook_boundary.events == [("secret",), ("secret",)]


@pytest.mark.parametrize(
    ("event", "payload", "message"),
    [
        ("", _valid_payload(), "X-GitHub-Event must be push"),
        ("ping", _valid_payload(), "X-GitHub-Event must be push"),
        (
            "push",
            {**_valid_payload(), "repository": {}},
            "Webhook repository identity does not match",
        ),
        (
            "push",
            {**_valid_payload(), "repository": {"id": True}},
            "Webhook repository identity does not match",
        ),
        (
            "push",
            {**_valid_payload(), "repository": {"id": str(_REPOSITORY_ID)}},
            "Webhook repository identity does not match",
        ),
        (
            "push",
            {**_valid_payload(), "repository": {"id": _REPOSITORY_ID + 1}},
            "Webhook repository identity does not match",
        ),
        (
            "push",
            {**_valid_payload(), "ref": None},
            "Webhook ref must be refs/heads/main",
        ),
        (
            "push",
            {**_valid_payload(), "ref": "refs/heads/release"},
            "Webhook ref must be refs/heads/main",
        ),
        (
            "push",
            {**_valid_payload(), "deleted": None},
            "Deleted refs cannot trigger deployment",
        ),
        (
            "push",
            {**_valid_payload(), "deleted": 0},
            "Deleted refs cannot trigger deployment",
        ),
        (
            "push",
            {**_valid_payload(), "deleted": True},
            "Deleted refs cannot trigger deployment",
        ),
        (
            "push",
            {**_valid_payload(), "after": None},
            "Webhook after must be a non-zero lowercase 40-hex commit SHA",
        ),
        (
            "push",
            {**_valid_payload(), "after": "0" * 40},
            "Webhook after must be a non-zero lowercase 40-hex commit SHA",
        ),
        (
            "push",
            {**_valid_payload(), "after": "A" * 40},
            "Webhook after must be a non-zero lowercase 40-hex commit SHA",
        ),
        (
            "push",
            {**_valid_payload(), "after": "a" * 39},
            "Webhook after must be a non-zero lowercase 40-hex commit SHA",
        ),
    ],
)
def test_semantic_rejections_and_order_are_exact(
    webhook_boundary: WebhookBoundary,
    event: str,
    payload: dict[str, object],
    message: str,
) -> None:
    body, headers = _request_parts(payload, event=event)
    if not event:
        headers.pop("X-GitHub-Event")

    response = _post(body, headers)

    assert response.status_code == 422
    assert response.json() == _error_payload("invalid_webhook", message)
    assert webhook_boundary.events == [("secret",)]


def test_ledger_unavailable_follows_job_allocation_and_becomes_503(
    webhook_boundary: WebhookBoundary,
) -> None:
    webhook_boundary.ledger.claim_error = CollaboratorFailure("ledger offline")
    body, headers = _request_parts()

    response = _post(body, headers)

    assert response.status_code == 503
    assert response.json() == _error_payload(
        "service_unavailable", "Webhook delivery ledger is unavailable"
    )
    assert [event[0] for event in webhook_boundary.events] == [
        "secret",
        "prepare",
        "claim",
    ]
    assert webhook_boundary.events[1] == ("prepare", "deploy", "github_webhook_hmac")


def test_ledger_composition_failure_has_the_same_unavailable_contract(
    webhook_boundary: WebhookBoundary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_ledger() -> RecordingLedger:
        raise CollaboratorFailure("composition offline")

    monkeypatch.setattr(logs_webhooks, "get_github_delivery_ledger", unavailable_ledger)
    body, headers = _request_parts()

    response = _post(body, headers)

    assert response.status_code == 503
    assert response.json() == _error_payload(
        "service_unavailable", "Webhook delivery ledger is unavailable"
    )
    assert [event[0] for event in webhook_boundary.events] == ["secret", "prepare"]


@pytest.mark.parametrize(
    "stored_status", ["accepted", "dispatched", "ignored", "failed"]
)
def test_replayed_claim_reuses_original_job_without_rate_or_dispatch(
    webhook_boundary: WebhookBoundary,
    stored_status: str,
) -> None:
    webhook_boundary.ledger.claim = DeliveryClaim(
        False, "delivery-1", "original-deploy-job", stored_status
    )
    body, headers = _request_parts()

    response = _post(body, headers)

    expected = {
        "status": "Webhook delivery already processed",
        "delivery_id": "delivery-1",
        "job_id": "original-deploy-job",
        "delivery_status": stored_status,
    }
    assert response.status_code == 200
    assert response.json() == expected
    assert [event[0] for event in webhook_boundary.events] == [
        "secret",
        "prepare",
        "claim",
        "audit",
    ]
    assert webhook_boundary.events[-1] == (
        "audit",
        "deploy",
        "succeeded",
        expected,
        "INFO",
    )


def test_success_preserves_claim_rate_audit_dispatch_mark_and_response_order(
    webhook_boundary: WebhookBoundary,
) -> None:
    body, headers = _request_parts()

    response = _post(body, headers)

    summary = {
        "source": "github_webhook",
        "delivery_id": "delivery-1",
        "event": "push",
        "repository_id": _REPOSITORY_ID,
        "commit_sha": _COMMIT_SHA,
        "ref": "refs/heads/main",
    }
    expected = {
        "status": "Deployment triggered",
        "job_id": "deploy-contract-job",
        "status_url": "/console/jobs/deploy-contract-job",
        "timestamp": "2026-08-23T10:11:12.345678Z",
    }
    assert response.status_code == 200
    assert response.json() == expected
    assert [event[0] for event in webhook_boundary.events] == [
        "secret",
        "prepare",
        "claim",
        "rate",
        "audit",
        "correlation",
        "job_service",
        "command",
        "dispatch",
        "mark",
        "clock",
        "audit",
    ]
    assert webhook_boundary.events[3] == ("rate", "deploy", "github_webhook_hmac")
    assert webhook_boundary.events[4] == ("audit", "deploy", "started", summary, "INFO")
    assert webhook_boundary.events[2] == (
        "claim",
        {
            "delivery_id": "delivery-1",
            "repository_id": _REPOSITORY_ID,
            "event_name": "push",
            "ref_name": "refs/heads/main",
            "commit_sha": _COMMIT_SHA,
            "job_id": "deploy-contract-job",
        },
    )
    dispatch = webhook_boundary.events[8][1]
    assert dispatch == {
        "job_id": "deploy-contract-job",
        "operation": "deploy",
        "dispatch_command": ["dispatch", "deploy-contract-job"],
        "requester": None,
        "request_id": _CORRELATION_ID,
        "correlation_id": _CORRELATION_ID,
        "request_summary": summary,
        "auth_scheme": "github_webhook_hmac",
        "dispatch_timeout_seconds": 37,
    }
    assert webhook_boundary.events[9] == ("mark", "delivery-1", "dispatched", None)
    assert webhook_boundary.events[-1] == (
        "audit",
        "deploy",
        "succeeded",
        expected,
        "INFO",
    )


def test_rate_failure_marks_failed_with_truncated_detail_and_re_raises(
    webhook_boundary: WebhookBoundary,
) -> None:
    detail = "x" * 1100
    webhook_boundary.rate_error = HTTPException(
        status_code=429, detail=detail, headers={"Retry-After": "7"}
    )
    body, headers = _request_parts()

    response = _post(body, headers)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    assert response.json() == _error_payload("rate_limited", detail)
    assert [event[0] for event in webhook_boundary.events] == [
        "secret",
        "prepare",
        "claim",
        "rate",
        "mark",
    ]
    assert webhook_boundary.events[-1] == ("mark", "delivery-1", "failed", "x" * 1000)


def test_only_operation_in_progress_dict_409_is_ignored(
    webhook_boundary: WebhookBoundary,
) -> None:
    webhook_boundary.dispatch_error = HTTPException(
        status_code=409,
        detail={"code": "operation_in_progress", "message": "busy"},
    )
    body, headers = _request_parts()

    response = _post(body, headers)

    expected = {
        "status": "Deployment already in progress; webhook delivery ignored.",
        "job_id": "deploy-contract-job",
        "delivery_id": "delivery-1",
        "commit_sha": _COMMIT_SHA,
        "timestamp": "2026-08-23T10:11:12.345678Z",
    }
    assert response.status_code == 200
    assert response.json() == expected
    assert [event[0] for event in webhook_boundary.events][-3:] == [
        "clock",
        "mark",
        "audit",
    ]
    assert webhook_boundary.events[-2] == ("mark", "delivery-1", "ignored", None)
    assert webhook_boundary.events[-1] == (
        "audit",
        "deploy",
        "succeeded",
        expected,
        "INFO",
    )


@pytest.mark.parametrize(
    "error",
    [
        HTTPException(
            status_code=409, detail={"code": "different_conflict", "message": "busy"}
        ),
        HTTPException(status_code=409, detail="operation_in_progress"),
        HTTPException(status_code=503, detail={"code": "operation_in_progress"}),
    ],
)
def test_other_http_dispatch_failures_mark_audit_and_re_raise_exactly(
    webhook_boundary: WebhookBoundary,
    error: HTTPException,
) -> None:
    webhook_boundary.dispatch_error = error
    body, headers = _request_parts()

    response = _post(body, headers)

    assert response.status_code == error.status_code
    assert [event[0] for event in webhook_boundary.events][-2:] == ["mark", "audit"]
    reason = str(error.detail)
    assert webhook_boundary.events[-2] == (
        "mark",
        "delivery-1",
        "failed",
        reason[:1000],
    )
    assert webhook_boundary.events[-1] == (
        "audit",
        "deploy",
        "failed",
        {"status_code": error.status_code, "error": reason},
        "ERROR",
    )


def test_general_dispatch_failure_marks_audits_and_propagates(
    webhook_boundary: WebhookBoundary,
) -> None:
    webhook_boundary.dispatch_error = CollaboratorFailure("dispatcher offline")
    body, headers = _request_parts()

    with pytest.raises(CollaboratorFailure, match="dispatcher offline"):
        _post(body, headers)

    assert webhook_boundary.events[-2] == (
        "mark",
        "delivery-1",
        "failed",
        "dispatcher offline",
    )
    assert webhook_boundary.events[-1] == (
        "audit",
        "deploy",
        "failed",
        {"status_code": 500, "error": "dispatcher offline"},
        "ERROR",
    )


def test_general_dispatch_failure_uses_the_generic_real_asgi_error_envelope(
    webhook_boundary: WebhookBoundary,
) -> None:
    webhook_boundary.dispatch_error = CollaboratorFailure("dispatcher offline")
    body, headers = _request_parts()

    response = _post(body, headers, raise_server_exceptions=False)

    assert response.status_code == 500
    assert response.json() == _error_payload(
        "internal_server_error", "Internal server error"
    )
    assert [event[0] for event in webhook_boundary.events][-2:] == ["mark", "audit"]


@pytest.mark.parametrize(
    ("failure_point", "expected_tail"),
    [
        ("rate_mark", ["rate", "mark"]),
        ("started_audit", ["rate", "audit"]),
        ("correlation", ["correlation", "mark", "audit"]),
        ("command", ["job_service", "command", "mark", "audit"]),
        ("success_mark", ["dispatch", "mark"]),
        ("success_clock", ["mark", "clock"]),
        ("success_audit", ["clock", "audit"]),
        ("replay_audit", ["claim", "audit"]),
        ("ignored_clock", ["dispatch", "clock"]),
        ("ignored_mark", ["clock", "mark"]),
        ("failed_mark", ["dispatch", "mark"]),
        ("failed_audit", ["mark", "audit"]),
    ],
)
def test_collaborator_failure_propagation_points_are_pinned(
    webhook_boundary: WebhookBoundary,
    failure_point: str,
    expected_tail: list[str],
) -> None:
    failure = CollaboratorFailure(failure_point)
    if failure_point == "rate_mark":
        webhook_boundary.rate_error = HTTPException(status_code=429, detail="limited")
        webhook_boundary.ledger.mark_errors["failed"] = failure
    elif failure_point == "started_audit":
        webhook_boundary.audit_errors["started"] = failure
    elif failure_point == "correlation":
        webhook_boundary.correlation_error = failure
    elif failure_point == "command":
        webhook_boundary.command_error = failure
    elif failure_point == "success_mark":
        webhook_boundary.ledger.mark_errors["dispatched"] = failure
    elif failure_point == "success_clock":
        webhook_boundary.clock_error = failure
    elif failure_point == "success_audit":
        webhook_boundary.audit_errors["succeeded"] = failure
    elif failure_point == "replay_audit":
        webhook_boundary.ledger.claim = DeliveryClaim(
            False, "delivery-1", "original-job", "dispatched"
        )
        webhook_boundary.audit_errors["succeeded"] = failure
    elif failure_point == "ignored_clock":
        webhook_boundary.dispatch_error = HTTPException(
            status_code=409, detail={"code": "operation_in_progress"}
        )
        webhook_boundary.clock_error = failure
    elif failure_point == "ignored_mark":
        webhook_boundary.dispatch_error = HTTPException(
            status_code=409, detail={"code": "operation_in_progress"}
        )
        webhook_boundary.ledger.mark_errors["ignored"] = failure
    elif failure_point == "failed_mark":
        webhook_boundary.dispatch_error = CollaboratorFailure("dispatch failed")
        webhook_boundary.ledger.mark_errors["failed"] = failure
    else:
        webhook_boundary.dispatch_error = CollaboratorFailure("dispatch failed")
        webhook_boundary.audit_errors["failed"] = failure

    body, headers = _request_parts()
    with pytest.raises(CollaboratorFailure, match=failure_point):
        _post(body, headers)

    assert [event[0] for event in webhook_boundary.events][
        -len(expected_tail) :
    ] == expected_tail
