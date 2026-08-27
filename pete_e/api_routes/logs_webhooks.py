import datetime
from typing import NoReturn

import fastapi
from fastapi import Header, HTTPException, Query, Request

from pete_e.application.github_deploy_webhook import (
    DeliveryLedgerUnavailable,
    DispatchHTTPFailure,
    GitHubDeliveryLedger,
    GitHubDeployCoordinator,
    GitHubPushCandidate,
    GitHubVerificationFailure,
    ParsedGitHubSignature,
    VerificationFailureCategory,
    VerifiedGitHubPush,
    authenticate_body,
    configured_deploy_ref,
    configured_repository_id,
    parse_push_candidate,
    parse_signature_header,
    verify_push_candidate,
)
from pete_e.api_routes.dependencies import (
    audit_command_event,
    configured_deploy_dispatch_command,
    configured_webhook_secret,
    enforce_command_rate_limit,
    get_github_delivery_ledger,
    get_job_service,
    prepare_job_context,
    validate_api_key,
)
from pete_e.api_errors import get_or_create_correlation_id
from pete_e.config import settings

router = fastapi.APIRouter()


def _configured_repository_id() -> int:
    try:
        return configured_repository_id(
            getattr(settings, "PETEEEBOT_GITHUB_REPOSITORY_ID", None)
        )
    except GitHubVerificationFailure as exc:
        _raise_verification_failure(exc)


def _configured_deploy_ref() -> str:
    try:
        return configured_deploy_ref(
            getattr(settings, "PETEEEBOT_GITHUB_DEPLOY_REF", "")
        )
    except GitHubVerificationFailure as exc:
        _raise_verification_failure(exc)


async def _read_bounded_body(request: Request) -> bytes:
    maximum = int(settings.PETEEEBOT_WEBHOOK_MAX_BODY_BYTES)
    raw_length = request.headers.get("Content-Length")
    if raw_length is not None:
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        if content_length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if content_length > maximum:
            raise HTTPException(status_code=413, detail="Webhook body too large")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(status_code=413, detail="Webhook body too large")
        body.extend(chunk)
    return bytes(body)


def _reject_webhook(message: str) -> NoReturn:
    raise HTTPException(
        status_code=422,
        detail={"code": "invalid_webhook", "message": message},
    )


def _raise_verification_failure(failure: GitHubVerificationFailure) -> NoReturn:
    if failure.category is VerificationFailureCategory.POLICY:
        _reject_webhook(failure.message)
    status_code = {
        VerificationFailureCategory.AUTHENTICATION: 403,
        VerificationFailureCategory.PAYLOAD: 400,
        VerificationFailureCategory.CONFIGURATION: 503,
    }[failure.category]
    raise HTTPException(status_code=status_code, detail=failure.message) from failure


def _parse_signature(signature: str | None) -> ParsedGitHubSignature:
    try:
        return parse_signature_header(signature)
    except GitHubVerificationFailure as exc:
        _raise_verification_failure(exc)


def _authenticate_signature(
    signature: ParsedGitHubSignature,
    body: bytes,
) -> None:
    try:
        authenticate_body(signature, body, configured_webhook_secret())
    except GitHubVerificationFailure as exc:
        _raise_verification_failure(exc)


def _parse_candidate(request: Request, body: bytes) -> GitHubPushCandidate:
    try:
        return parse_push_candidate(
            body,
            event_name=str(request.headers.get("X-GitHub-Event") or ""),
            delivery_id=str(request.headers.get("X-GitHub-Delivery") or ""),
        )
    except GitHubVerificationFailure as exc:
        _raise_verification_failure(exc)


def _verify_candidate(candidate: GitHubPushCandidate) -> VerifiedGitHubPush:
    repository_id = _configured_repository_id()
    deploy_ref = _configured_deploy_ref()
    try:
        return verify_push_candidate(
            candidate,
            expected_repository_id=repository_id,
            deploy_ref=deploy_ref,
        )
    except GitHubVerificationFailure as exc:
        _raise_verification_failure(exc)


def _delivery_ledger() -> GitHubDeliveryLedger:
    try:
        return get_github_delivery_ledger()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Webhook delivery ledger is unavailable",
        ) from exc


def _utc_timestamp() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


class _RequestDeployCollaborators:
    def __init__(self, request: Request, job_id: str) -> None:
        self.request = request
        self.job_id = job_id

    def rate_check(self) -> None:
        enforce_command_rate_limit(self.request, "deploy")

    def dispatch(self, summary: dict[str, object]) -> None:
        try:
            correlation_id = get_or_create_correlation_id(self.request)
            get_job_service().dispatch_external(
                job_id=self.job_id,
                operation="deploy",
                dispatch_command=configured_deploy_dispatch_command(self.job_id),
                requester=None,
                request_id=correlation_id,
                correlation_id=correlation_id,
                request_summary=summary,
                auth_scheme=getattr(
                    getattr(self.request, "state", None),
                    "auth_scheme",
                    None,
                ),
                dispatch_timeout_seconds=settings.PETEEEBOT_DEPLOY_DISPATCH_TIMEOUT_SECONDS,
            )
        except HTTPException as exc:
            raise DispatchHTTPFailure(
                status_code=getattr(exc, "status_code", 500),
                detail=getattr(exc, "detail", {}),
                original=exc,
            ) from exc

    def audit(
        self,
        outcome: str,
        summary: dict[str, object],
        level: str,
    ) -> None:
        audit_command_event(
            self.request,
            command="deploy",
            outcome=outcome,
            summary=summary,
            level=level,
        )


def _coordinate_delivery(
    request: Request,
    delivery: VerifiedGitHubPush,
    job_id: str,
) -> dict[str, object]:
    collaborators = _RequestDeployCollaborators(request, job_id)
    coordinator = GitHubDeployCoordinator(
        ledger=_delivery_ledger(),
        rate_check=collaborators.rate_check,
        dispatch=collaborators.dispatch,
        audit=collaborators.audit,
        timestamp=_utc_timestamp,
    )
    try:
        return coordinator.coordinate(delivery, job_id=job_id).response
    except DeliveryLedgerUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Webhook delivery ledger is unavailable",
        ) from exc
    except DispatchHTTPFailure as exc:
        raise exc.original


def read_recent_log_lines(lines: int) -> dict[str, object]:
    log_path = settings.log_path
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_path}")
    try:
        with log_path.open("r", encoding="utf-8") as log_file:
            log_lines = log_file.readlines()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"path": str(log_path), "lines": [line.rstrip("\n") for line in log_lines[-lines:]]}


@router.get("/logs")
def logs(request: Request, x_api_key: str = Header(None), lines: int = Query(50, ge=1, le=1000)):
    validate_api_key(request, x_api_key)
    return read_recent_log_lines(lines)


@router.post("/webhook")
async def github_webhook(request: Request) -> dict[str, object]:
    signature = _parse_signature(request.headers.get("X-Hub-Signature-256"))
    body = await _read_bounded_body(request)
    _authenticate_signature(signature, body)
    if getattr(request, "state", None) is not None:
        setattr(request.state, "auth_scheme", "github_webhook_hmac")
    delivery = _verify_candidate(_parse_candidate(request, body))
    job_id = prepare_job_context(request, "deploy")
    return _coordinate_delivery(request, delivery, job_id)
