from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest
from psycopg_pool import ConnectionPool

from pete_e import api
from pete_e.api_routes import dependencies, logs_webhooks
from pete_e.infrastructure.edge_security_repository import (
    PostgresEdgeSecurityRepository,
    RateLimitRule,
)


pytestmark = pytest.mark.integration


def _pool(dsn: str) -> ConnectionPool:
    return ConnectionPool(conninfo=dsn, min_size=1, max_size=4, open=True)


def _rate_limited_app(operation: str) -> FastAPI:
    app = FastAPI()

    @app.post("/limited")
    def limited(request: Request):
        dependencies.enforce_command_rate_limit(
            request,
            operation,
            max_requests=1,
            window_seconds=300,
        )
        return {"ok": True}

    return app


def test_rate_limits_are_shared_across_instances_and_survive_repository_restart(
    postgres_test_dsn: str,
) -> None:
    subject = f"integration-{uuid4()}"
    rule = RateLimitRule(
        scope="command:integration:account",
        subject=subject,
        max_requests=1,
        window_seconds=300,
    )
    first_pool = _pool(postgres_test_dsn)
    second_pool = _pool(postgres_test_dsn)
    try:
        first_instance = PostgresEdgeSecurityRepository(first_pool)
        second_instance = PostgresEdgeSecurityRepository(second_pool)

        assert first_instance.consume_rate_limits((rule,)) is None
        shared_decision = second_instance.consume_rate_limits((rule,))
        assert shared_decision is not None
        assert shared_decision.code == "rate_limited"
    finally:
        first_pool.close()
        second_pool.close()

    restarted_pool = _pool(postgres_test_dsn)
    try:
        restarted_instance = PostgresEdgeSecurityRepository(restarted_pool)
        restart_decision = restarted_instance.consume_rate_limits((rule,))
        assert restart_decision is not None
        assert restart_decision.code == "rate_limited"
    finally:
        restarted_pool.close()


def test_rate_limit_is_shared_across_fastapi_instances_and_restart(
    postgres_test_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = f"integration-{uuid4()}"
    first_pool = _pool(postgres_test_dsn)
    second_pool = _pool(postgres_test_dsn)
    try:
        first_repository = PostgresEdgeSecurityRepository(first_pool)
        second_repository = PostgresEdgeSecurityRepository(second_pool)
        monkeypatch.setattr(
            dependencies, "get_edge_security_repository", lambda: first_repository
        )
        with TestClient(
            _rate_limited_app(operation), client=("203.0.113.50", 55000)
        ) as first_client:
            first = first_client.post("/limited")

        monkeypatch.setattr(
            dependencies, "get_edge_security_repository", lambda: second_repository
        )
        with TestClient(
            _rate_limited_app(operation), client=("203.0.113.50", 55001)
        ) as second_client:
            second = second_client.post("/limited")

        assert first.status_code == 200
        assert second.status_code == 429
    finally:
        first_pool.close()
        second_pool.close()

    restarted_pool = _pool(postgres_test_dsn)
    try:
        restarted_repository = PostgresEdgeSecurityRepository(restarted_pool)
        monkeypatch.setattr(
            dependencies, "get_edge_security_repository", lambda: restarted_repository
        )
        with TestClient(
            _rate_limited_app(operation), client=("203.0.113.50", 55002)
        ) as restarted_client:
            restarted = restarted_client.post("/limited")

        assert restarted.status_code == 429
    finally:
        restarted_pool.close()


def test_concurrent_github_delivery_claim_has_one_winner(
    postgres_test_dsn: str,
) -> None:
    delivery_id = f"delivery-{uuid4()}"
    first_pool = _pool(postgres_test_dsn)
    second_pool = _pool(postgres_test_dsn)
    repositories = (
        PostgresEdgeSecurityRepository(first_pool),
        PostgresEdgeSecurityRepository(second_pool),
    )

    def claim(index: int):
        return repositories[index % 2].claim_github_delivery(
            delivery_id=delivery_id,
            repository_id=1044067254,
            event_name="push",
            ref_name="refs/heads/main",
            commit_sha="a" * 40,
            job_id=f"deploy-{uuid4()}",
        )

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            claims = list(executor.map(claim, range(16)))

        winners = [claim for claim in claims if claim.accepted]
        assert len(winners) == 1
        assert {claim.job_id for claim in claims} == {winners[0].job_id}

        replay_with_altered_header = repositories[0].claim_github_delivery(
            delivery_id=f"{delivery_id}-altered",
            repository_id=1044067254,
            event_name="push",
            ref_name="refs/heads/main",
            commit_sha="a" * 40,
            job_id=f"deploy-{uuid4()}",
        )
        assert replay_with_altered_header.accepted is False
        assert replay_with_altered_header.job_id == winners[0].job_id
    finally:
        first_pool.close()
        second_pool.close()


@pytest.mark.parametrize("status", ["dispatched", "ignored", "failed"])
def test_github_delivery_marks_are_visible_to_replay_claims(
    postgres_test_dsn: str,
    status: str,
) -> None:
    pool = _pool(postgres_test_dsn)
    repository = PostgresEdgeSecurityRepository(pool)
    delivery_id = f"delivery-{uuid4()}"
    commit_sha = hashlib.sha256(delivery_id.encode()).hexdigest()[:40]
    try:
        accepted = repository.claim_github_delivery(
            delivery_id=delivery_id,
            repository_id=1044067254,
            event_name="push",
            ref_name="refs/heads/main",
            commit_sha=commit_sha,
            job_id=f"deploy-{uuid4()}",
        )
        repository.mark_github_delivery(
            delivery_id,
            status=status,
            failure_reason="dispatch failed" if status == "failed" else None,
        )
        replay = repository.claim_github_delivery(
            delivery_id=delivery_id,
            repository_id=1044067254,
            event_name="push",
            ref_name="refs/heads/main",
            commit_sha=commit_sha,
            job_id=f"deploy-{uuid4()}",
        )

        assert accepted.accepted is True
        assert replay.accepted is False
        assert replay.job_id == accepted.job_id
        assert replay.status == status
    finally:
        pool.close()


def test_real_asgi_webhook_dispatches_through_postgres_delivery_ledger(
    postgres_test_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _pool(postgres_test_dsn)
    repository = PostgresEdgeSecurityRepository(pool)
    delivery_id = f"handler-{uuid4()}"
    job_id = f"deploy-{uuid4()}"
    commit_sha = hashlib.sha256(delivery_id.encode()).hexdigest()[:40]
    secret = b"postgres-handler-webhook-secret"
    dispatched: list[dict[str, object]] = []

    class JobService:
        def dispatch_external(self, **kwargs: object) -> None:
            dispatched.append(kwargs)

    monkeypatch.setattr(logs_webhooks, "configured_webhook_secret", lambda: secret)
    monkeypatch.setattr(
        logs_webhooks.settings,
        "PETEEEBOT_GITHUB_REPOSITORY_ID",
        1044067254,
    )
    monkeypatch.setattr(
        logs_webhooks.settings,
        "PETEEEBOT_GITHUB_DEPLOY_REF",
        "refs/heads/main",
    )
    monkeypatch.setattr(
        logs_webhooks.settings,
        "PETEEEBOT_WEBHOOK_MAX_BODY_BYTES",
        4096,
    )
    monkeypatch.setattr(logs_webhooks, "get_github_delivery_ledger", lambda: repository)
    monkeypatch.setattr(logs_webhooks, "prepare_job_context", lambda *_args: job_id)
    monkeypatch.setattr(
        logs_webhooks,
        "enforce_command_rate_limit",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        logs_webhooks, "audit_command_event", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(logs_webhooks, "get_job_service", lambda: JobService())
    monkeypatch.setattr(
        logs_webhooks,
        "configured_deploy_dispatch_command",
        lambda configured_job_id: ["dispatch", configured_job_id],
    )
    payload = {
        "repository": {"id": 1044067254},
        "ref": "refs/heads/main",
        "after": commit_sha,
        "deleted": False,
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    headers = {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": delivery_id,
    }
    try:
        with TestClient(api.app) as client:
            accepted = client.post("/api/v1/webhook", content=body, headers=headers)
            replayed = client.post("/api/v1/webhook", content=body, headers=headers)

        assert accepted.status_code == 200
        assert accepted.json()["status"] == "Deployment triggered"
        assert accepted.json()["job_id"] == job_id
        assert replayed.status_code == 200
        assert replayed.json() == {
            "status": "Webhook delivery already processed",
            "delivery_id": delivery_id,
            "job_id": job_id,
            "delivery_status": "dispatched",
        }
        assert len(dispatched) == 1
        assert dispatched[0]["request_summary"] == {
            "source": "github_webhook",
            "delivery_id": delivery_id,
            "event": "push",
            "repository_id": 1044067254,
            "commit_sha": commit_sha,
            "ref": "refs/heads/main",
        }
    finally:
        pool.close()
