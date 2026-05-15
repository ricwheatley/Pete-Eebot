from __future__ import annotations

import threading
import time

import pytest

from pete_e.api_routes import dependencies, status_sync
from pete_e.application.concurrency_guard import (
    HighRiskOperationGuard,
    OperationInProgress,
    high_risk_operation_guard,
)


class _Request:
    query_params: dict[str, str] = {}


def _wait_until_released(timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while high_risk_operation_guard.active_operation is not None:
        if time.monotonic() >= deadline:
            raise AssertionError("guard did not release")
        time.sleep(0.01)


def test_high_risk_guard_rejects_overlap() -> None:
    guard = HighRiskOperationGuard()
    guard.acquire("sync")
    try:
        with pytest.raises(OperationInProgress) as exc:
            guard.acquire("plan")
    finally:
        guard.release()

    assert exc.value.requested_operation == "plan"
    assert exc.value.active_operation == "sync"


def test_sync_endpoint_returns_conflict_when_high_risk_operation_active(monkeypatch) -> None:
    calls = {"sync": 0}
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(
        status_sync,
        "run_sync_with_retries",
        lambda days, retries: calls.__setitem__("sync", calls["sync"] + 1),
    )

    high_risk_operation_guard.acquire("plan")
    try:
        with pytest.raises(status_sync.HTTPException) as exc:
            status_sync.sync(
                request=_Request(),
                x_api_key="test-key",
                days=1,
                retries=1,
            )
    finally:
        high_risk_operation_guard.release()

    assert exc.value.status_code == 409
    assert exc.value.detail["requested_operation"] == "sync"
    assert exc.value.detail["active_operation"] == "plan"
    assert calls["sync"] == 0


def test_spawned_high_risk_process_holds_guard_until_wait_completes(monkeypatch) -> None:
    release_process = threading.Event()

    class _Process:
        def wait(self) -> int:
            release_process.wait(timeout=1)
            return 0

    monkeypatch.setattr(dependencies.subprocess, "Popen", lambda command: _Process())

    dependencies.start_guarded_high_risk_process("plan", ["pete", "plan"])
    try:
        with pytest.raises(dependencies.HTTPException) as exc:
            dependencies.run_guarded_high_risk_operation("sync", lambda: None)
    finally:
        release_process.set()
        _wait_until_released()

    assert exc.value.status_code == 409
    assert exc.value.detail["requested_operation"] == "sync"
    assert exc.value.detail["active_operation"] == "plan"
