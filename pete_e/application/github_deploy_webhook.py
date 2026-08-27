"""Verify and coordinate replay-safe GitHub deployment deliveries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
import re
from typing import Any, Protocol


ZERO_COMMIT_SHA = "0" * 40
COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
DELIVERY_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,128}")


class VerificationFailureCategory(Enum):
    AUTHENTICATION = "authentication"
    PAYLOAD = "payload"
    CONFIGURATION = "configuration"
    POLICY = "policy"


class GitHubVerificationFailure(ValueError):
    """A typed verification rejection for translation by a protocol adapter."""

    def __init__(self, category: VerificationFailureCategory, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass(frozen=True, slots=True)
class ParsedGitHubSignature:
    algorithm: str
    digest: str


@dataclass(frozen=True, slots=True)
class GitHubPushCandidate:
    event_name: str
    delivery_id: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class VerifiedGitHubPush:
    delivery_id: str
    event_name: str
    repository_id: int
    ref_name: str
    commit_sha: str

    def summary(self) -> dict[str, object]:
        return {
            "source": "github_webhook",
            "delivery_id": self.delivery_id,
            "event": self.event_name,
            "repository_id": self.repository_id,
            "commit_sha": self.commit_sha,
            "ref": self.ref_name,
        }


def parse_signature_header(signature: str | None) -> ParsedGitHubSignature:
    if not signature:
        raise GitHubVerificationFailure(
            VerificationFailureCategory.AUTHENTICATION,
            "Missing signature",
        )
    try:
        algorithm, digest = signature.split("=")
    except ValueError as exc:
        raise GitHubVerificationFailure(
            VerificationFailureCategory.AUTHENTICATION,
            "Bad signature format",
        ) from exc
    if algorithm != "sha256":
        raise GitHubVerificationFailure(
            VerificationFailureCategory.AUTHENTICATION,
            "Unsupported signature type",
        )
    return ParsedGitHubSignature(algorithm=algorithm, digest=digest)


def authenticate_body(
    signature: ParsedGitHubSignature,
    body: bytes,
    secret: bytes,
) -> None:
    mac = hmac.new(secret, msg=body, digestmod=hashlib.sha256)
    if not hmac.compare_digest(mac.hexdigest(), signature.digest):
        raise GitHubVerificationFailure(
            VerificationFailureCategory.AUTHENTICATION,
            "Invalid signature",
        )


def parse_push_candidate(
    body: bytes,
    *,
    event_name: str,
    delivery_id: str,
) -> GitHubPushCandidate:
    if DELIVERY_ID_PATTERN.fullmatch(delivery_id) is None:
        raise GitHubVerificationFailure(
            VerificationFailureCategory.POLICY,
            "Missing or invalid X-GitHub-Delivery",
        )
    try:
        decoded_payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GitHubVerificationFailure(
            VerificationFailureCategory.PAYLOAD,
            "Invalid JSON payload",
        ) from exc
    if not isinstance(decoded_payload, dict):
        raise GitHubVerificationFailure(
            VerificationFailureCategory.PAYLOAD,
            "JSON payload must be an object",
        )
    return GitHubPushCandidate(
        event_name=event_name,
        delivery_id=delivery_id,
        payload=decoded_payload,
    )


def configured_repository_id(raw_repository_id: Any) -> int:
    if raw_repository_id is None or int(raw_repository_id) <= 0:
        raise GitHubVerificationFailure(
            VerificationFailureCategory.CONFIGURATION,
            "PETEEEBOT_GITHUB_REPOSITORY_ID is not configured",
        )
    return int(raw_repository_id)


def configured_deploy_ref(raw_deploy_ref: object) -> str:
    deploy_ref = str(raw_deploy_ref or "").strip()
    if deploy_ref != "refs/heads/main":
        raise GitHubVerificationFailure(
            VerificationFailureCategory.CONFIGURATION,
            "PETEEEBOT_GITHUB_DEPLOY_REF must be refs/heads/main",
        )
    return deploy_ref


def verify_push_candidate(
    candidate: GitHubPushCandidate,
    *,
    expected_repository_id: int,
    deploy_ref: str,
) -> VerifiedGitHubPush:
    repository = candidate.payload.get("repository")
    repository_id = repository.get("id") if isinstance(repository, dict) else None
    commit_sha = candidate.payload.get("after")
    ref_name = candidate.payload.get("ref")

    _verify_event(candidate.event_name)
    _verify_repository(repository_id, expected_repository_id)
    verified_ref = _verify_ref(ref_name, deploy_ref)
    _verify_not_deleted(candidate.payload.get("deleted"))
    verified_commit = _verify_commit(commit_sha)
    return VerifiedGitHubPush(
        delivery_id=candidate.delivery_id,
        event_name=candidate.event_name,
        repository_id=expected_repository_id,
        ref_name=verified_ref,
        commit_sha=verified_commit,
    )


def _policy_failure(message: str) -> GitHubVerificationFailure:
    return GitHubVerificationFailure(VerificationFailureCategory.POLICY, message)


def _verify_event(event_name: str) -> None:
    if event_name != "push":
        raise _policy_failure("X-GitHub-Event must be push")


def _verify_repository(repository_id: object, expected_repository_id: int) -> None:
    if type(repository_id) is not int or repository_id != expected_repository_id:
        raise _policy_failure("Webhook repository identity does not match")


def _verify_ref(ref_name: object, deploy_ref: str) -> str:
    if not isinstance(ref_name, str) or ref_name != deploy_ref:
        raise _policy_failure(f"Webhook ref must be {deploy_ref}")
    return ref_name


def _verify_not_deleted(deleted: object) -> None:
    if deleted is not False:
        raise _policy_failure("Deleted refs cannot trigger deployment")


def _verify_commit(commit_sha: object) -> str:
    if (
        not isinstance(commit_sha, str)
        or commit_sha == ZERO_COMMIT_SHA
        or COMMIT_SHA_PATTERN.fullmatch(commit_sha) is None
    ):
        raise _policy_failure(
            "Webhook after must be a non-zero lowercase 40-hex commit SHA"
        )
    return commit_sha


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    accepted: bool
    delivery_id: str
    job_id: str
    status: str


class GitHubDeliveryLedger(Protocol):
    def claim_github_delivery(
        self,
        *,
        delivery_id: str,
        repository_id: int,
        event_name: str,
        ref_name: str,
        commit_sha: str,
        job_id: str,
    ) -> DeliveryClaim: ...

    def mark_github_delivery(
        self,
        delivery_id: str,
        *,
        status: str,
        failure_reason: str | None = None,
    ) -> None: ...


class DeliveryOutcomeKind(Enum):
    REPLAYED = "replayed"
    IGNORED = "ignored"
    DISPATCHED = "dispatched"


@dataclass(frozen=True, slots=True)
class GitHubDeliveryOutcome:
    kind: DeliveryOutcomeKind
    response: dict[str, object]


class DeliveryLedgerUnavailable(RuntimeError):
    pass


class DispatchHTTPFailure(RuntimeError):
    """Framework-neutral description of an HTTP failure from dispatch setup."""

    def __init__(self, status_code: int, detail: object, original: Exception) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.original = original


RateCheck = Callable[[], None]
Dispatch = Callable[[dict[str, object]], None]
Audit = Callable[[str, dict[str, object], str], None]
Timestamp = Callable[[], str]


class GitHubDeployCoordinator:
    def __init__(
        self,
        *,
        ledger: GitHubDeliveryLedger,
        rate_check: RateCheck,
        dispatch: Dispatch,
        audit: Audit,
        timestamp: Timestamp,
    ) -> None:
        self._ledger = ledger
        self._rate_check = rate_check
        self._dispatch = dispatch
        self._audit = audit
        self._timestamp = timestamp

    def coordinate(
        self,
        delivery: VerifiedGitHubPush,
        *,
        job_id: str,
    ) -> GitHubDeliveryOutcome:
        claim = self._claim(delivery, job_id)
        if not claim.accepted:
            return self._replayed(delivery, claim)
        return self._coordinate_claimed(delivery, job_id)

    def _claim(self, delivery: VerifiedGitHubPush, job_id: str) -> DeliveryClaim:
        try:
            return self._ledger.claim_github_delivery(
                delivery_id=delivery.delivery_id,
                repository_id=delivery.repository_id,
                event_name=delivery.event_name,
                ref_name=delivery.ref_name,
                commit_sha=delivery.commit_sha,
                job_id=job_id,
            )
        except Exception as exc:
            raise DeliveryLedgerUnavailable from exc

    def _replayed(
        self,
        delivery: VerifiedGitHubPush,
        claim: DeliveryClaim,
    ) -> GitHubDeliveryOutcome:
        response: dict[str, object] = {
            "status": "Webhook delivery already processed",
            "delivery_id": delivery.delivery_id,
            "job_id": claim.job_id,
            "delivery_status": claim.status,
        }
        self._audit("succeeded", response, "INFO")
        return GitHubDeliveryOutcome(DeliveryOutcomeKind.REPLAYED, response)

    def _coordinate_claimed(
        self,
        delivery: VerifiedGitHubPush,
        job_id: str,
    ) -> GitHubDeliveryOutcome:
        summary = delivery.summary()
        self._check_rate(delivery)
        self._audit("started", summary, "INFO")
        return self._dispatch_claimed(delivery, job_id, summary)

    def _check_rate(self, delivery: VerifiedGitHubPush) -> None:
        try:
            self._rate_check()
        except Exception as exc:
            self._ledger.mark_github_delivery(
                delivery.delivery_id,
                status="failed",
                failure_reason=_failure_reason(exc),
            )
            raise

    def _dispatch_claimed(
        self,
        delivery: VerifiedGitHubPush,
        job_id: str,
        summary: dict[str, object],
    ) -> GitHubDeliveryOutcome:
        try:
            self._dispatch(summary)
        except DispatchHTTPFailure as exc:
            return self._handle_http_failure(delivery, job_id, exc)
        except Exception as exc:
            self._record_failure(delivery, exc)
            raise
        return self._dispatched(delivery, job_id)

    def _handle_http_failure(
        self,
        delivery: VerifiedGitHubPush,
        job_id: str,
        failure: DispatchHTTPFailure,
    ) -> GitHubDeliveryOutcome:
        if _is_operation_in_progress(failure):
            return self._ignored(delivery, job_id)
        self._record_failure(delivery, failure.original)
        raise failure

    def _record_failure(
        self,
        delivery: VerifiedGitHubPush,
        failure: Exception,
    ) -> None:
        error = str(getattr(failure, "detail", failure))
        self._ledger.mark_github_delivery(
            delivery.delivery_id,
            status="failed",
            failure_reason=error[:1000],
        )
        self._audit(
            "failed",
            {
                "status_code": getattr(failure, "status_code", 500),
                "error": error,
            },
            "ERROR",
        )

    def _ignored(
        self,
        delivery: VerifiedGitHubPush,
        job_id: str,
    ) -> GitHubDeliveryOutcome:
        response: dict[str, object] = {
            "status": "Deployment already in progress; webhook delivery ignored.",
            "job_id": job_id,
            "delivery_id": delivery.delivery_id,
            "commit_sha": delivery.commit_sha,
            "timestamp": self._timestamp(),
        }
        self._ledger.mark_github_delivery(delivery.delivery_id, status="ignored")
        self._audit("succeeded", response, "INFO")
        return GitHubDeliveryOutcome(DeliveryOutcomeKind.IGNORED, response)

    def _dispatched(
        self,
        delivery: VerifiedGitHubPush,
        job_id: str,
    ) -> GitHubDeliveryOutcome:
        self._ledger.mark_github_delivery(delivery.delivery_id, status="dispatched")
        response: dict[str, object] = {
            "status": "Deployment triggered",
            "job_id": job_id,
            "status_url": f"/console/jobs/{job_id}",
            "timestamp": self._timestamp(),
        }
        self._audit("succeeded", response, "INFO")
        return GitHubDeliveryOutcome(DeliveryOutcomeKind.DISPATCHED, response)


def _failure_reason(failure: Exception) -> str:
    return str(getattr(failure, "detail", failure))[:1000]


def _is_operation_in_progress(failure: DispatchHTTPFailure) -> bool:
    return (
        failure.status_code == 409
        and isinstance(failure.detail, dict)
        and failure.detail.get("code") == "operation_in_progress"
    )
