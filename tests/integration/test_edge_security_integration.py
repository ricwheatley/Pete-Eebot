from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest
from psycopg_pool import ConnectionPool

from pete_e.api_routes import dependencies
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
        monkeypatch.setattr(dependencies, "get_edge_security_repository", lambda: first_repository)
        with TestClient(_rate_limited_app(operation), client=("203.0.113.50", 55000)) as first_client:
            first = first_client.post("/limited")

        monkeypatch.setattr(dependencies, "get_edge_security_repository", lambda: second_repository)
        with TestClient(_rate_limited_app(operation), client=("203.0.113.50", 55001)) as second_client:
            second = second_client.post("/limited")

        assert first.status_code == 200
        assert second.status_code == 429
    finally:
        first_pool.close()
        second_pool.close()

    restarted_pool = _pool(postgres_test_dsn)
    try:
        restarted_repository = PostgresEdgeSecurityRepository(restarted_pool)
        monkeypatch.setattr(dependencies, "get_edge_security_repository", lambda: restarted_repository)
        with TestClient(_rate_limited_app(operation), client=("203.0.113.50", 55002)) as restarted_client:
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
