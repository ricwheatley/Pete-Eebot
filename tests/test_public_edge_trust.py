from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from types import SimpleNamespace
import time

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from pete_e import api
from pete_e.api_routes import auth, dependencies, logs_webhooks, status_sync
from pete_e.application.api_services import StatusService
from pete_e.client_identity import client_identity
from pete_e.cli import status as status_checks
from pete_e.cli.status import CheckResult
from tests.edge_security_fakes import InMemoryEdgeSecurityRepository


pytestmark = pytest.mark.contract

_WEBHOOK_SECRET = b"edge-test-webhook-secret"
_REPOSITORY_ID = 1044067254
_COMMIT_SHA = "a" * 40


def _identity_app() -> FastAPI:
    identity_app = FastAPI()

    @identity_app.get("/identity")
    def identity(request: Request):
        return {"client": client_identity(request)}

    return identity_app


def test_untrusted_direct_peer_cannot_spoof_xff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    with TestClient(_identity_app(), client=("203.0.113.9", 55000)) as client:
        response = client.get("/identity", headers={"X-Forwarded-For": "198.51.100.77"})

    assert response.status_code == 200
    assert response.json() == {"client": "203.0.113.9"}


def test_trusted_single_and_multi_proxy_chains_resolve_right_to_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dependencies.settings,
        "PETEEEBOT_TRUSTED_PROXY_CIDRS",
        "127.0.0.1/32,10.0.0.0/8",
    )
    with TestClient(_identity_app(), client=("127.0.0.1", 55000)) as client:
        single = client.get("/identity", headers={"X-Forwarded-For": "198.51.100.20"})
        multiple = client.get(
            "/identity",
            headers={"X-Forwarded-For": "198.51.100.21, 10.1.2.3"},
        )
        attacker_prefix = client.get(
            "/identity",
            headers={"X-Forwarded-For": "192.0.2.66, 198.51.100.22"},
        )
        malformed = client.get(
            "/identity",
            headers={"X-Forwarded-For": "not-an-ip"},
        )

    assert single.json()["client"] == "198.51.100.20"
    assert multiple.json()["client"] == "198.51.100.21"
    assert attacker_prefix.json()["client"] == "198.51.100.22"
    assert malformed.json()["client"] == "127.0.0.1"


def test_spoofed_xff_rotation_cannot_bypass_login_account_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryEdgeSecurityRepository()
    monkeypatch.setattr(dependencies, "get_edge_security_repository", lambda: repository)
    monkeypatch.setattr(auth, "get_user_service", lambda: SimpleNamespace(authenticate_user=lambda *_args: None))
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_TRUSTED_PROXY_CIDRS", "")
    monkeypatch.setattr(dependencies, "DEFAULT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(dependencies, "DEFAULT_LOGIN_BACKOFF_BASE_SECONDS", 0.0)
    monkeypatch.setattr(dependencies, "DEFAULT_LOGIN_LOCKOUT_SECONDS", 120.0)

    with TestClient(api.app, client=("203.0.113.10", 55000)) as client:
        first = client.post(
            "/auth/login",
            json={"login": "pete", "password": "wrong"},
            headers={"X-Forwarded-For": "198.51.100.1"},
        )
        second = client.post(
            "/auth/login",
            json={"login": "pete", "password": "wrong"},
            headers={"X-Forwarded-For": "198.51.100.2"},
        )

    assert first.status_code == 401
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "login_locked"


def test_repeated_public_readyz_never_constructs_external_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"database": 0}

    def inspect_database(*_args, **_kwargs):
        calls["database"] += 1
        return SimpleNamespace(compatible=True, head_revision="edge-head")

    def external_client(*_args, **_kwargs):
        raise AssertionError("public readiness constructed an external provider client")

    monkeypatch.setattr(status_checks, "inspect_database", inspect_database)
    monkeypatch.setattr(status_checks, "get_database_url", lambda: "postgresql://local/readiness")
    for name in (
        "AppleDropboxClient",
        "WithingsClient",
        "TelegramClient",
        "WgerClient",
        "OllamaChatClient",
    ):
        monkeypatch.setattr(status_checks, name, external_client)

    with TestClient(api.app) as client:
        responses = [client.get("/readyz?timeout=0.5") for _ in range(3)]

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert calls == {"database": 3}


def test_stale_schema_fails_real_readyz_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        status_checks,
        "inspect_database",
        lambda *_args, **_kwargs: SimpleNamespace(
            compatible=False,
            state="stale",
            current_revision="old",
            head_revision="head",
            detail="one migration pending",
        ),
    )
    monkeypatch.setattr(status_checks, "get_database_url", lambda: "postgresql://local/readiness")

    with TestClient(api.app) as client:
        response = client.get("/readyz?timeout=0.5")

    assert response.status_code == 503
    assert response.json() == {"ok": False, "status": "unhealthy"}


def test_readiness_deadline_bounds_a_stalled_local_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        status_checks,
        "check_database",
        lambda _timeout: time.sleep(0.2) or CheckResult("DB", True, "late"),
    )

    started = time.perf_counter()
    results = status_checks.run_readiness_checks(timeout=0.02)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.1
    assert results == [CheckResult("DB", False, "readiness deadline exceeded")]


def test_deep_status_requires_authentication_uses_cache_and_is_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_calls = []
    service = StatusService(dal=None)
    service.run_checks = lambda timeout: provider_calls.append(timeout) or [
        CheckResult("DB", True, "schema head"),
        CheckResult("Withings", True, "reachable"),
    ]
    repository = InMemoryEdgeSecurityRepository()
    monkeypatch.setattr(status_sync, "get_status_service", lambda: service)
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "operator-key")
    monkeypatch.setattr(status_sync.settings, "PETEEEBOT_DEEP_STATUS_CACHE_SECONDS", 30.0)
    monkeypatch.setattr(dependencies, "get_edge_security_repository", lambda: repository)
    monkeypatch.setattr(
        status_sync,
        "enforce_command_rate_limit",
        lambda request, operation: dependencies.enforce_command_rate_limit(
            request,
            operation,
            max_requests=2,
            window_seconds=60,
        ),
    )

    with TestClient(api.app, client=("203.0.113.12", 55000)) as client:
        unauthenticated = client.get("/api/v1/status?timeout=0.5")
        first = client.get(
            "/api/v1/status?timeout=0.5",
            headers={"X-API-Key": "operator-key"},
        )
        cached = client.get(
            "/api/v1/status?timeout=0.5",
            headers={"X-API-Key": "operator-key"},
        )
        limited = client.get(
            "/api/v1/status?timeout=0.5",
            headers={"X-API-Key": "operator-key"},
        )

    assert unauthenticated.status_code == 401
    assert first.status_code == 200
    assert cached.status_code == 200
    assert limited.status_code == 429
    assert provider_calls == [0.5]


def _signed_request(payload: dict[str, object], *, event: str = "push", delivery: str = "delivery-1"):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(_WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": f"sha256={digest}",
    }


def _valid_payload() -> dict[str, object]:
    return {
        "repository": {"id": _REPOSITORY_ID},
        "ref": "refs/heads/main",
        "after": _COMMIT_SHA,
        "deleted": False,
    }


@pytest.fixture()
def webhook_boundary(monkeypatch: pytest.MonkeyPatch):
    repository = InMemoryEdgeSecurityRepository()
    enqueued = []

    class JobService:
        def dispatch_external(self, **kwargs):
            enqueued.append(kwargs)

    monkeypatch.setattr(logs_webhooks, "configured_webhook_secret", lambda: _WEBHOOK_SECRET)
    monkeypatch.setattr(logs_webhooks.settings, "PETEEEBOT_GITHUB_REPOSITORY_ID", _REPOSITORY_ID)
    monkeypatch.setattr(logs_webhooks.settings, "PETEEEBOT_GITHUB_DEPLOY_REF", "refs/heads/main")
    monkeypatch.setattr(logs_webhooks.settings, "PETEEEBOT_WEBHOOK_MAX_BODY_BYTES", 4096)
    monkeypatch.setattr(logs_webhooks, "get_github_delivery_ledger", lambda: repository)
    monkeypatch.setattr(logs_webhooks, "enforce_command_rate_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(logs_webhooks, "prepare_job_context", lambda *_args: "deploy-edge-job")
    monkeypatch.setattr(logs_webhooks, "get_job_service", lambda: JobService())
    monkeypatch.setattr(
        logs_webhooks,
        "configured_deploy_dispatch_command",
        lambda job_id: ["dispatch", job_id],
    )
    monkeypatch.setattr(logs_webhooks, "audit_command_event", lambda *_args, **_kwargs: None)
    return repository, enqueued


@pytest.mark.parametrize(
    ("event", "mutate"),
    [
        ("ping", lambda payload: payload),
        ("push", lambda payload: payload.update(repository={"id": _REPOSITORY_ID + 1})),
        ("push", lambda payload: payload.update(ref="refs/heads/release")),
        ("push", lambda payload: payload.update(deleted=True)),
        ("push", lambda payload: payload.update(after="0" * 40)),
        ("push", lambda payload: payload.update(after="$(touch /tmp/pwned)")),
    ],
)
def test_webhook_rejects_wrong_semantics(
    webhook_boundary,
    event: str,
    mutate,
) -> None:
    _repository, enqueued = webhook_boundary
    payload = _valid_payload()
    mutate(payload)
    body, headers = _signed_request(payload, event=event)

    with TestClient(api.app) as client:
        response = client.post("/api/v1/webhook", content=body, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_webhook"
    assert enqueued == []


def test_webhook_rejects_missing_invalid_signature_and_oversized_body(
    webhook_boundary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repository, enqueued = webhook_boundary
    body, headers = _signed_request(_valid_payload())
    with TestClient(api.app) as client:
        missing = client.post("/api/v1/webhook", content=body)
        invalid = client.post(
            "/api/v1/webhook",
            content=body,
            headers={**headers, "X-Hub-Signature-256": "sha256=invalid"},
        )
        monkeypatch.setattr(logs_webhooks.settings, "PETEEEBOT_WEBHOOK_MAX_BODY_BYTES", 32)
        oversized = client.post("/api/v1/webhook", content=body, headers=headers)

    assert missing.status_code == 403
    assert invalid.status_code == 403
    assert oversized.status_code == 413
    assert enqueued == []


def test_webhook_rejects_missing_delivery_id(webhook_boundary) -> None:
    _repository, enqueued = webhook_boundary
    body, headers = _signed_request(_valid_payload())
    headers.pop("X-GitHub-Delivery")

    with TestClient(api.app) as client:
        response = client.post("/api/v1/webhook", content=body, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_webhook"
    assert enqueued == []


def test_webhook_replay_and_concurrent_replay_enqueue_once(webhook_boundary) -> None:
    repository, enqueued = webhook_boundary
    body, headers = _signed_request(_valid_payload(), delivery="concurrent-delivery")

    with TestClient(api.app) as client:
        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(
                executor.map(
                    lambda _index: client.post(
                        "/api/v1/webhook",
                        content=body,
                        headers=headers,
                    ),
                    range(8),
                )
            )
        replay = client.post("/api/v1/webhook", content=body, headers=headers)
        altered_delivery_replay = client.post(
            "/api/v1/webhook",
            content=body,
            headers={**headers, "X-GitHub-Delivery": "altered-delivery-id"},
        )

    assert all(response.status_code == 200 for response in responses)
    assert sum(response.json()["status"] == "Deployment triggered" for response in responses) == 1
    assert replay.json()["status"] == "Webhook delivery already processed"
    assert altered_delivery_replay.json()["status"] == "Webhook delivery already processed"
    assert len(enqueued) == 1
    assert enqueued[0]["request_summary"]["commit_sha"] == _COMMIT_SHA
    assert repository.deliveries["concurrent-delivery"]["status"] == "dispatched"
