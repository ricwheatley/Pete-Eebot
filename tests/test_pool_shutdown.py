import pytest

from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import _closes_postgres_pool
from pete_e.application.sync import run_sync_with_retries


def test_closes_pool_decorator_runs_close_even_on_error(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrator_module, "close_pool", lambda: calls.append("closed"))

    class Dummy:
        @_closes_postgres_pool
        def succeed(self):
            return "ok"

        @_closes_postgres_pool
        def fail(self):
            raise RuntimeError("boom")

    dummy = Dummy()

    assert dummy.succeed() == "ok"
    assert calls == ["closed"]

    calls.clear()
    with pytest.raises(RuntimeError):
        dummy.fail()
    assert calls == ["closed"]


def test_run_sync_with_retries_closes_pool(monkeypatch):
    close_calls = []
    monkeypatch.setattr(orchestrator_module, "close_pool", lambda: close_calls.append("closed"))

    class StubOrchestrator:
        @_closes_postgres_pool
        def run_daily_sync(self, days):
            return True, [], {}, []

    monkeypatch.setattr("pete_e.application.sync.Orchestrator", lambda: StubOrchestrator())

    result = run_sync_with_retries(days=1, retries=1, delay=1)

    assert result.success is True
    assert close_calls == ["closed"]
