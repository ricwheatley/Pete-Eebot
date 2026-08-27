from __future__ import annotations

import ast
from dataclasses import dataclass, field
import hashlib
import hmac
from pathlib import Path
from typing import Any

import pytest

from pete_e.application.github_deploy_webhook import (
    DeliveryClaim,
    DeliveryLedgerUnavailable,
    DeliveryOutcomeKind,
    DispatchHTTPFailure,
    GitHubDeployCoordinator,
    GitHubVerificationFailure,
    VerificationFailureCategory,
    VerifiedGitHubPush,
    authenticate_body,
    configured_deploy_ref,
    configured_repository_id,
    parse_push_candidate,
    parse_signature_header,
    verify_push_candidate,
)


pytestmark = pytest.mark.unit

_REPOSITORY_ID = 1044067254
_COMMIT_SHA = "a" * 40
_BODY = (
    b'{"repository":{"id":1044067254},"ref":"refs/heads/main",'
    b'"after":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","deleted":false}'
)
_SECRET = b"pure-verifier-secret"


def _failure(call, category: VerificationFailureCategory, message: str) -> None:
    with pytest.raises(GitHubVerificationFailure) as captured:
        call()
    assert captured.value.category is category
    assert captured.value.message == message
    assert str(captured.value) == message


@pytest.mark.parametrize(
    ("signature", "message"),
    [
        (None, "Missing signature"),
        ("", "Missing signature"),
        ("sha256", "Bad signature format"),
        ("sha256=a=b", "Bad signature format"),
        ("sha1=digest", "Unsupported signature type"),
    ],
)
def test_parse_signature_failures(signature: str | None, message: str) -> None:
    _failure(
        lambda: parse_signature_header(signature),
        VerificationFailureCategory.AUTHENTICATION,
        message,
    )


def test_authenticate_body_accepts_only_the_exact_hmac() -> None:
    digest = hmac.new(_SECRET, _BODY, hashlib.sha256).hexdigest()
    signature = parse_signature_header(f"sha256={digest}")

    assert signature.algorithm == "sha256"
    authenticate_body(signature, _BODY, _SECRET)
    _failure(
        lambda: authenticate_body(signature, _BODY + b" ", _SECRET),
        VerificationFailureCategory.AUTHENTICATION,
        "Invalid signature",
    )


@pytest.mark.parametrize(
    ("body", "delivery_id", "category", "message"),
    [
        (
            _BODY,
            "bad_value",
            VerificationFailureCategory.POLICY,
            "Missing or invalid X-GitHub-Delivery",
        ),
        (
            b"\xff",
            "delivery-1",
            VerificationFailureCategory.PAYLOAD,
            "Invalid JSON payload",
        ),
        (
            b"{",
            "delivery-1",
            VerificationFailureCategory.PAYLOAD,
            "Invalid JSON payload",
        ),
        (
            b"[]",
            "delivery-1",
            VerificationFailureCategory.PAYLOAD,
            "JSON payload must be an object",
        ),
    ],
)
def test_parse_push_candidate_failures(
    body: bytes,
    delivery_id: str,
    category: VerificationFailureCategory,
    message: str,
) -> None:
    _failure(
        lambda: parse_push_candidate(
            body,
            event_name="push",
            delivery_id=delivery_id,
        ),
        category,
        message,
    )


def test_parse_and_verify_push_produces_an_immutable_typed_delivery() -> None:
    candidate = parse_push_candidate(
        _BODY,
        event_name="push",
        delivery_id="delivery-1",
    )
    delivery = verify_push_candidate(
        candidate,
        expected_repository_id=_REPOSITORY_ID,
        deploy_ref="refs/heads/main",
    )

    assert delivery == VerifiedGitHubPush(
        delivery_id="delivery-1",
        event_name="push",
        repository_id=_REPOSITORY_ID,
        ref_name="refs/heads/main",
        commit_sha=_COMMIT_SHA,
    )
    assert delivery.summary() == {
        "source": "github_webhook",
        "delivery_id": "delivery-1",
        "event": "push",
        "repository_id": _REPOSITORY_ID,
        "commit_sha": _COMMIT_SHA,
        "ref": "refs/heads/main",
    }
    with pytest.raises(AttributeError):
        delivery.commit_sha = "b" * 40  # type: ignore[misc]


@pytest.mark.parametrize("raw", [None, 0, -1, "0"])
def test_repository_configuration_rejects_missing_and_non_positive_values(
    raw: object,
) -> None:
    _failure(
        lambda: configured_repository_id(raw),
        VerificationFailureCategory.CONFIGURATION,
        "PETEEEBOT_GITHUB_REPOSITORY_ID is not configured",
    )


def test_repository_configuration_preserves_conversion_behavior() -> None:
    assert configured_repository_id(str(_REPOSITORY_ID)) == _REPOSITORY_ID
    with pytest.raises(ValueError, match="invalid literal"):
        configured_repository_id("not-an-integer")


@pytest.mark.parametrize("raw", [None, "", "refs/heads/release"])
def test_deploy_ref_configuration_rejects_any_non_main_ref(raw: object) -> None:
    _failure(
        lambda: configured_deploy_ref(raw),
        VerificationFailureCategory.CONFIGURATION,
        "PETEEEBOT_GITHUB_DEPLOY_REF must be refs/heads/main",
    )


def test_deploy_ref_configuration_strips_surrounding_whitespace() -> None:
    assert configured_deploy_ref(" refs/heads/main ") == "refs/heads/main"


@pytest.mark.parametrize(
    ("event", "payload", "message"),
    [
        ("ping", {}, "X-GitHub-Event must be push"),
        ("push", {}, "Webhook repository identity does not match"),
        (
            "push",
            {"repository": {"id": True}},
            "Webhook repository identity does not match",
        ),
        (
            "push",
            {"repository": {"id": _REPOSITORY_ID}, "ref": None},
            "Webhook ref must be refs/heads/main",
        ),
        (
            "push",
            {"repository": {"id": _REPOSITORY_ID}, "ref": "refs/heads/release"},
            "Webhook ref must be refs/heads/main",
        ),
        (
            "push",
            {
                "repository": {"id": _REPOSITORY_ID},
                "ref": "refs/heads/main",
                "deleted": True,
            },
            "Deleted refs cannot trigger deployment",
        ),
        (
            "push",
            {
                "repository": {"id": _REPOSITORY_ID},
                "ref": "refs/heads/main",
                "deleted": False,
                "after": None,
            },
            "Webhook after must be a non-zero lowercase 40-hex commit SHA",
        ),
        (
            "push",
            {
                "repository": {"id": _REPOSITORY_ID},
                "ref": "refs/heads/main",
                "deleted": False,
                "after": "0" * 40,
            },
            "Webhook after must be a non-zero lowercase 40-hex commit SHA",
        ),
        (
            "push",
            {
                "repository": {"id": _REPOSITORY_ID},
                "ref": "refs/heads/main",
                "deleted": False,
                "after": "A" * 40,
            },
            "Webhook after must be a non-zero lowercase 40-hex commit SHA",
        ),
    ],
)
def test_push_policy_failures_are_ordered(
    event: str,
    payload: dict[str, object],
    message: str,
) -> None:
    candidate = parse_push_candidate(
        json_bytes(payload),
        event_name=event,
        delivery_id="delivery-1",
    )
    _failure(
        lambda: verify_push_candidate(
            candidate,
            expected_repository_id=_REPOSITORY_ID,
            deploy_ref="refs/heads/main",
        ),
        VerificationFailureCategory.POLICY,
        message,
    )


def json_bytes(payload: dict[str, object]) -> bytes:
    import json

    return json.dumps(payload, separators=(",", ":")).encode()


@dataclass
class RecordingLedger:
    events: list[tuple[Any, ...]]
    claim: DeliveryClaim = field(
        default_factory=lambda: DeliveryClaim(True, "delivery-1", "job-1", "accepted")
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
        if status in self.mark_errors:
            raise self.mark_errors[status]


@dataclass
class CoordinatorHarness:
    events: list[tuple[Any, ...]] = field(default_factory=list)
    rate_error: Exception | None = None
    dispatch_error: Exception | None = None
    audit_errors: dict[str, Exception] = field(default_factory=dict)
    clock_error: Exception | None = None

    def __post_init__(self) -> None:
        self.ledger = RecordingLedger(self.events)

    def rate(self) -> None:
        self.events.append(("rate",))
        if self.rate_error is not None:
            raise self.rate_error

    def dispatch(self, summary: dict[str, object]) -> None:
        self.events.append(("dispatch", summary))
        if self.dispatch_error is not None:
            raise self.dispatch_error

    def audit(self, outcome: str, summary: dict[str, object], level: str) -> None:
        self.events.append(("audit", outcome, summary, level))
        if outcome in self.audit_errors:
            raise self.audit_errors[outcome]

    def timestamp(self) -> str:
        self.events.append(("clock",))
        if self.clock_error is not None:
            raise self.clock_error
        return "2026-08-23T10:11:12Z"

    def coordinator(self) -> GitHubDeployCoordinator:
        return GitHubDeployCoordinator(
            ledger=self.ledger,
            rate_check=self.rate,
            dispatch=self.dispatch,
            audit=self.audit,
            timestamp=self.timestamp,
        )


def _delivery() -> VerifiedGitHubPush:
    return VerifiedGitHubPush(
        delivery_id="delivery-1",
        event_name="push",
        repository_id=_REPOSITORY_ID,
        ref_name="refs/heads/main",
        commit_sha=_COMMIT_SHA,
    )


def test_coordinator_claims_then_dispatches_and_marks() -> None:
    harness = CoordinatorHarness()

    outcome = harness.coordinator().coordinate(_delivery(), job_id="job-1")

    assert outcome.kind is DeliveryOutcomeKind.DISPATCHED
    assert outcome.response == {
        "status": "Deployment triggered",
        "job_id": "job-1",
        "status_url": "/console/jobs/job-1",
        "timestamp": "2026-08-23T10:11:12Z",
    }
    assert [event[0] for event in harness.events] == [
        "claim",
        "rate",
        "audit",
        "dispatch",
        "mark",
        "clock",
        "audit",
    ]
    assert harness.events[0][1] == {
        "delivery_id": "delivery-1",
        "repository_id": _REPOSITORY_ID,
        "event_name": "push",
        "ref_name": "refs/heads/main",
        "commit_sha": _COMMIT_SHA,
        "job_id": "job-1",
    }


def test_coordinator_wraps_only_claim_failure_as_ledger_unavailable() -> None:
    harness = CoordinatorHarness()
    harness.ledger.claim_error = RuntimeError("offline")

    with pytest.raises(DeliveryLedgerUnavailable) as captured:
        harness.coordinator().coordinate(_delivery(), job_id="job-1")

    assert isinstance(captured.value.__cause__, RuntimeError)
    assert [event[0] for event in harness.events] == ["claim"]


def test_coordinator_replay_reuses_claim_job_and_status() -> None:
    harness = CoordinatorHarness()
    harness.ledger.claim = DeliveryClaim(False, "delivery-1", "original-job", "failed")

    outcome = harness.coordinator().coordinate(_delivery(), job_id="new-job")

    assert outcome.kind is DeliveryOutcomeKind.REPLAYED
    assert outcome.response == {
        "status": "Webhook delivery already processed",
        "delivery_id": "delivery-1",
        "job_id": "original-job",
        "delivery_status": "failed",
    }
    assert [event[0] for event in harness.events] == ["claim", "audit"]


class _DetailedFailure(RuntimeError):
    detail = "x" * 1100
    status_code = 429


def test_rate_failure_is_marked_with_detail_before_original_is_raised() -> None:
    harness = CoordinatorHarness(rate_error=_DetailedFailure("limited"))

    with pytest.raises(_DetailedFailure):
        harness.coordinator().coordinate(_delivery(), job_id="job-1")

    assert [event[0] for event in harness.events] == ["claim", "rate", "mark"]
    assert harness.events[-1] == ("mark", "delivery-1", "failed", "x" * 1000)


def test_ignored_http_conflict_timestamps_then_marks_and_audits() -> None:
    harness = CoordinatorHarness()
    original = RuntimeError("busy")
    harness.dispatch_error = DispatchHTTPFailure(
        409,
        {"code": "operation_in_progress", "message": "busy"},
        original,
    )

    outcome = harness.coordinator().coordinate(_delivery(), job_id="job-1")

    assert outcome.kind is DeliveryOutcomeKind.IGNORED
    assert outcome.response == {
        "status": "Deployment already in progress; webhook delivery ignored.",
        "job_id": "job-1",
        "delivery_id": "delivery-1",
        "commit_sha": _COMMIT_SHA,
        "timestamp": "2026-08-23T10:11:12Z",
    }
    assert [event[0] for event in harness.events][-3:] == ["clock", "mark", "audit"]


@pytest.mark.parametrize(
    ("status_code", "detail"),
    [
        (500, {"code": "operation_in_progress"}),
        (409, "operation_in_progress"),
        (409, {"code": "different"}),
    ],
)
def test_non_ignored_http_failures_mark_and_audit_before_wrapper_is_raised(
    status_code: int,
    detail: object,
) -> None:
    harness = CoordinatorHarness()
    original = _DetailedFailure("original")
    original.status_code = status_code
    original.detail = detail
    wrapper = DispatchHTTPFailure(status_code, detail, original)
    harness.dispatch_error = wrapper

    with pytest.raises(DispatchHTTPFailure) as captured:
        harness.coordinator().coordinate(_delivery(), job_id="job-1")

    assert captured.value is wrapper
    assert captured.value.original is original
    assert [event[0] for event in harness.events][-2:] == ["mark", "audit"]
    assert harness.events[-1] == (
        "audit",
        "failed",
        {"status_code": status_code, "error": str(detail)},
        "ERROR",
    )


def test_general_dispatch_failure_uses_exception_text_and_default_status() -> None:
    message = "y" * 1100
    harness = CoordinatorHarness(dispatch_error=RuntimeError(message))

    with pytest.raises(RuntimeError, match="y{1100}"):
        harness.coordinator().coordinate(_delivery(), job_id="job-1")

    assert harness.events[-2] == ("mark", "delivery-1", "failed", "y" * 1000)
    assert harness.events[-1] == (
        "audit",
        "failed",
        {"status_code": 500, "error": message},
        "ERROR",
    )


@pytest.mark.parametrize(
    ("point", "tail"),
    [
        ("rate_mark", ["rate", "mark"]),
        ("started_audit", ["rate", "audit"]),
        ("dispatch_mark", ["dispatch", "mark"]),
        ("dispatch_audit", ["mark", "audit"]),
        ("success_mark", ["dispatch", "mark"]),
        ("success_clock", ["mark", "clock"]),
        ("success_audit", ["clock", "audit"]),
        ("replay_audit", ["claim", "audit"]),
        ("ignored_clock", ["dispatch", "clock"]),
        ("ignored_mark", ["clock", "mark"]),
        ("ignored_audit", ["mark", "audit"]),
    ],
)
def test_coordinator_collaborator_failure_points_are_exact(
    point: str,
    tail: list[str],
) -> None:
    harness = CoordinatorHarness()
    failure = RuntimeError(point)
    if point == "rate_mark":
        harness.rate_error = RuntimeError("limited")
        harness.ledger.mark_errors["failed"] = failure
    elif point == "started_audit":
        harness.audit_errors["started"] = failure
    elif point == "dispatch_mark":
        harness.dispatch_error = RuntimeError("dispatch failed")
        harness.ledger.mark_errors["failed"] = failure
    elif point == "dispatch_audit":
        harness.dispatch_error = RuntimeError("dispatch failed")
        harness.audit_errors["failed"] = failure
    elif point == "success_mark":
        harness.ledger.mark_errors["dispatched"] = failure
    elif point == "success_clock":
        harness.clock_error = failure
    elif point == "success_audit":
        harness.audit_errors["succeeded"] = failure
    elif point == "replay_audit":
        harness.ledger.claim = DeliveryClaim(
            False, "delivery-1", "original-job", "accepted"
        )
        harness.audit_errors["succeeded"] = failure
    else:
        harness.dispatch_error = DispatchHTTPFailure(
            409,
            {"code": "operation_in_progress"},
            RuntimeError("busy"),
        )
        if point == "ignored_clock":
            harness.clock_error = failure
        elif point == "ignored_mark":
            harness.ledger.mark_errors["ignored"] = failure
        else:
            harness.audit_errors["succeeded"] = failure

    with pytest.raises(RuntimeError, match=point):
        harness.coordinator().coordinate(_delivery(), job_id="job-1")

    assert [event[0] for event in harness.events][-len(tail) :] == tail


def test_application_boundary_has_no_framework_or_infrastructure_imports() -> None:
    module_path = Path("pete_e/application/github_deploy_webhook.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )

    forbidden_prefixes = (
        "fastapi",
        "starlette",
        "psycopg",
        "pete_e.api",
        "pete_e.api_routes",
        "pete_e.cli",
        "pete_e.infrastructure",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imports)
