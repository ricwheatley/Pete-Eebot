from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading

from psycopg_pool import ConnectionPool
import pytest

from pete_e.infrastructure.job_repository import PostgresApplicationJobRepository


pytestmark = pytest.mark.integration


def _create(repository: PostgresApplicationJobRepository, job_id: str, operation: str = "sync"):
    return repository.create(
        job_id=job_id,
        operation=operation,
        requester_user_id=None,
        requester_username=None,
        auth_scheme="integration-test",
        request_id=job_id,
        correlation_id=job_id,
        request_summary={},
    )


def test_concurrent_postgres_claim_has_one_winner(postgres_test_dsn: str) -> None:
    pool = ConnectionPool(conninfo=postgres_test_dsn, min_size=2, max_size=4, open=True)
    try:
        repository = PostgresApplicationJobRepository(pool=pool)
        _create(repository, "ownership-concurrent-claim")
        barrier = threading.Barrier(2)

        def claim(worker_id: str):
            barrier.wait(timeout=2)
            return repository.claim(
                "ownership-concurrent-claim",
                worker_id=worker_id,
                lease_seconds=30,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, ("postgres-worker-a", "postgres-worker-b")))

        winners = [result for result in results if result is not None]
        assert len(winners) == 1
        assert winners[0].ownership_token == 1
        assert repository.get("ownership-concurrent-claim").worker_id == winners[0].worker_id
    finally:
        pool.close()


def test_postgres_fencing_rejects_stale_terminal_updates_and_lock_release(
    postgres_test_dsn: str,
) -> None:
    pool = ConnectionPool(conninfo=postgres_test_dsn, min_size=1, max_size=3, open=True)
    try:
        repository = PostgresApplicationJobRepository(pool=pool)
        _create(repository, "ownership-reclaimed")
        old = repository.claim(
            "ownership-reclaimed",
            worker_id="postgres-old-worker",
            lease_seconds=30,
        )
        assert old is not None and old.ownership_token == 1
        assert repository.acquire_high_risk_operation_lock(
            operation="sync",
            job_id=old.id,
            worker_id=str(old.worker_id),
            ownership_token=old.ownership_token,
            lease_seconds=30,
        )
        with pool.connection() as connection:
            connection.execute(
                "UPDATE application_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
                (old.id,),
            )
            connection.execute(
                "UPDATE application_operation_locks SET expires_at = now() - interval '1 second' WHERE job_id = %s",
                (old.id,),
            )

        new = repository.claim(
            old.id,
            worker_id="postgres-new-worker",
            lease_seconds=30,
        )
        assert new is not None and new.ownership_token == 2
        assert repository.acquire_high_risk_operation_lock(
            operation="sync",
            job_id=new.id,
            worker_id=str(new.worker_id),
            ownership_token=new.ownership_token,
            lease_seconds=30,
        )
        assert not repository.heartbeat(
            job_id=old.id,
            worker_id=str(old.worker_id),
            ownership_token=old.ownership_token,
            lease_seconds=30,
        )
        for status in ("succeeded", "failed"):
            assert not repository.complete(
                old.id,
                worker_id=str(old.worker_id),
                ownership_token=old.ownership_token,
                status=status,
                completed_at=datetime.now(timezone.utc),
                exit_code=None,
                result_summary="stale result",
                stdout_summary=None,
                stderr_summary=None,
                failure_reason=None,
            )
        assert not repository.release_high_risk_operation_lock(
            job_id=old.id,
            worker_id=str(old.worker_id),
            ownership_token=old.ownership_token,
        )
        active_lock = repository.get_active_high_risk_operation_lock()
        assert active_lock is not None
        assert active_lock.worker_id == "postgres-new-worker"
        assert active_lock.ownership_token == 2

        assert repository.complete(
            new.id,
            worker_id=str(new.worker_id),
            ownership_token=new.ownership_token,
            status="succeeded",
            completed_at=datetime.now(timezone.utc),
            exit_code=0,
            result_summary="new owner completed",
            stdout_summary=None,
            stderr_summary=None,
            failure_reason=None,
        )
        assert repository.get_active_high_risk_operation_lock() is None
    finally:
        pool.close()


def test_postgres_heartbeat_renewal_prevents_recovery(
    postgres_test_dsn: str,
) -> None:
    pool = ConnectionPool(conninfo=postgres_test_dsn, min_size=1, max_size=2, open=True)
    try:
        repository = PostgresApplicationJobRepository(pool=pool)
        _create(repository, "ownership-heartbeat")
        claim = repository.claim(
            "ownership-heartbeat",
            worker_id="postgres-heartbeat-worker",
            lease_seconds=5,
        )
        assert claim is not None and claim.lease_expires_at is not None
        assert repository.acquire_high_risk_operation_lock(
            operation="sync",
            job_id=claim.id,
            worker_id=str(claim.worker_id),
            ownership_token=int(claim.ownership_token),
            lease_seconds=5,
        )
        original_expiry = claim.lease_expires_at
        assert repository.heartbeat(
            job_id=claim.id,
            worker_id=str(claim.worker_id),
            ownership_token=int(claim.ownership_token),
            lease_seconds=60,
            progress={"phase": "still-active"},
        )

        recovered = repository.recover_stale_operations(
            stale_before=original_expiry + timedelta(microseconds=1),
            queued_before=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        current = repository.get(claim.id)
        assert recovered == 0
        assert current is not None and current.status == "running"
        assert current.progress_summary == {"phase": "still-active"}
        assert current.lease_expires_at > original_expiry
        assert repository.complete(
            current.id,
            worker_id=str(current.worker_id),
            ownership_token=int(current.ownership_token),
            status="succeeded",
            completed_at=datetime.now(timezone.utc),
            exit_code=0,
            result_summary="heartbeat test complete",
            stdout_summary=None,
            stderr_summary=None,
            failure_reason=None,
        )
    finally:
        pool.close()


def test_postgres_concurrent_operation_lock_acquisition_has_one_owner(
    postgres_test_dsn: str,
) -> None:
    pool = ConnectionPool(conninfo=postgres_test_dsn, min_size=2, max_size=4, open=True)
    try:
        repository = PostgresApplicationJobRepository(pool=pool)
        claims = []
        for suffix in ("a", "b"):
            job = _create(repository, f"ownership-lock-{suffix}", operation=f"operation-{suffix}")
            claims.append(
                repository.claim(job.id, worker_id=f"postgres-worker-{suffix}", lease_seconds=30)
            )
        barrier = threading.Barrier(2)

        def acquire(claim):
            assert claim is not None
            barrier.wait(timeout=2)
            return repository.acquire_high_risk_operation_lock(
                operation=claim.operation,
                job_id=claim.id,
                worker_id=str(claim.worker_id),
                ownership_token=int(claim.ownership_token),
                lease_seconds=30,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            locks = list(executor.map(acquire, claims))

        winners = [operation_lock for operation_lock in locks if operation_lock is not None]
        assert len(winners) == 1
        persisted = repository.get_active_high_risk_operation_lock()
        assert persisted is not None
        assert persisted.job_id == winners[0].job_id
        assert persisted.ownership_token == winners[0].ownership_token
        winning_claim = next(claim for claim in claims if claim.id == persisted.job_id)
        assert repository.complete(
            winning_claim.id,
            worker_id=str(winning_claim.worker_id),
            ownership_token=int(winning_claim.ownership_token),
            status="succeeded",
            completed_at=datetime.now(timezone.utc),
            exit_code=0,
            result_summary="concurrent lock test complete",
            stdout_summary=None,
            stderr_summary=None,
            failure_reason=None,
        )
    finally:
        pool.close()


def test_postgres_dispatch_handoff_transfers_job_and_lock_token(
    postgres_test_dsn: str,
) -> None:
    pool = ConnectionPool(conninfo=postgres_test_dsn, min_size=1, max_size=2, open=True)
    try:
        repository = PostgresApplicationJobRepository(pool=pool)
        job = _create(repository, "ownership-handoff", operation="deploy")
        dispatch = repository.claim(
            job.id,
            worker_id="postgres-api-dispatcher",
            lease_seconds=30,
        )
        assert dispatch is not None and dispatch.ownership_token == 1
        assert repository.acquire_high_risk_operation_lock(
            operation="deploy",
            job_id=dispatch.id,
            worker_id=str(dispatch.worker_id),
            ownership_token=dispatch.ownership_token,
            lease_seconds=30,
        )
        assert repository.heartbeat(
            job_id=dispatch.id,
            worker_id=str(dispatch.worker_id),
            ownership_token=dispatch.ownership_token,
            lease_seconds=30,
            progress={"operation": "deploy", "phase": "dispatching"},
        )

        worker = repository.handoff_claim(
            dispatch.id,
            from_worker_id=str(dispatch.worker_id),
            from_ownership_token=dispatch.ownership_token,
            to_worker_id="postgres-independent-deploy-worker",
            lease_seconds=30,
        )
        assert worker is not None and worker.ownership_token == 2
        operation_lock = repository.get_active_high_risk_operation_lock()
        assert operation_lock is not None
        assert operation_lock.worker_id == worker.worker_id
        assert operation_lock.ownership_token == worker.ownership_token
        assert worker.progress_summary["phase"] == "running"
        assert (
            repository.handoff_claim(
                worker.id,
                from_worker_id=str(worker.worker_id),
                from_ownership_token=int(worker.ownership_token),
                to_worker_id="postgres-duplicate-deploy-worker",
                lease_seconds=30,
            )
            is None
        )
        assert not repository.complete(
            dispatch.id,
            worker_id=str(dispatch.worker_id),
            ownership_token=dispatch.ownership_token,
            status="succeeded",
            completed_at=datetime.now(timezone.utc),
            exit_code=0,
            result_summary="stale dispatch result",
            stdout_summary=None,
            stderr_summary=None,
            failure_reason=None,
        )
        assert repository.complete(
            worker.id,
            worker_id=str(worker.worker_id),
            ownership_token=int(worker.ownership_token),
            status="succeeded",
            completed_at=datetime.now(timezone.utc),
            exit_code=0,
            result_summary="independent worker complete",
            stdout_summary=None,
            stderr_summary=None,
            failure_reason=None,
        )
        assert repository.get_active_high_risk_operation_lock() is None
    finally:
        pool.close()
