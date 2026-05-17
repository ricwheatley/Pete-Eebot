from unittest.mock import MagicMock

# Import the modules we need to test and mock
from pete_e.application.orchestrator import Orchestrator
from pete_e.application.sync import run_sync_with_retries
from pete_e.infrastructure import postgres_dal
from pete_e.infrastructure.postgres_dal import PostgresDal
from tests.di_utils import build_stub_container


class _FakePool:
    def __init__(self, *, closed: bool = False) -> None:
        self.closed = closed

    def close(self) -> None:
        self.closed = True


def test_orchestrator_close_method_closes_dal(monkeypatch):
    """
    Tests that the Orchestrator's close method correctly calls the close method on its DAL.
    This replaces the old decorator test.
    """
    # Create a mock DAL with a close method we can track
    mock_dal = MagicMock()
    mock_dal.close = MagicMock()

    # We need to provide all required arguments to the Orchestrator constructor
    mock_wger_client = MagicMock()
    mock_plan_service = MagicMock()
    mock_export_service = MagicMock()

    # Instantiate the orchestrator with our mock DAL and other services
    container = build_stub_container(
        dal=mock_dal,
        wger_client=mock_wger_client,
        plan_service=mock_plan_service,
        export_service=mock_export_service,
    )
    orchestrator = Orchestrator(container=container)

    # Call the method we want to test
    orchestrator.close()

    # Assert that the DAL's close method was called exactly once
    mock_dal.close.assert_called_once()


def test_run_sync_with_retries_closes_orchestrator(monkeypatch):
    """
    Tests that the main sync function closes the orchestrator after execution,
    both on success and failure.
    """
    close_calls = []

    # Stub the Orchestrator to control its behavior
    class StubOrchestrator:
        def __init__(self):
            # This flag will let us simulate a failure
            self.should_fail = False
            """Initialize this object."""

        def run_daily_sync(self, days):
            if self.should_fail:
                raise RuntimeError("Simulated sync failure")
            # Return a successful result tuple
            return True, [], {}, []
            """Perform run daily sync."""

        def close(self):
            # Record when the close method is called
            close_calls.append("closed")
            """Perform close."""
        """Represent StubOrchestrator."""

    # The _build_orchestrator factory in the sync module is the key to mocking
    stub_instance = StubOrchestrator()
    monkeypatch.setattr(
        "pete_e.application.sync._build_orchestrator", lambda: stub_instance
    )

    # --- Test 1: Success case ---
    result = run_sync_with_retries(days=1, retries=1, delay=1)

    assert result.success is True
    # Verify that close was called after the successful run
    assert close_calls == ["closed"]

    # --- Test 2: Failure case ---
    close_calls.clear()  # Reset for the next run
    stub_instance.should_fail = True

    # The sync will fail, but the finally block should still close the resources
    result = run_sync_with_retries(days=1, retries=1, delay=1)

    assert result.success is False
    # Verify that close was called even after the failure
    assert close_calls == ["closed"]


def test_default_dal_close_does_not_close_shared_global_pool(monkeypatch):
    shared_pool = _FakePool()
    monkeypatch.setattr(postgres_dal, "_pool", shared_pool)

    dal = PostgresDal()
    dal.close()

    assert shared_pool.closed is False


def test_get_pool_recreates_closed_global_pool(monkeypatch):
    closed_pool = _FakePool(closed=True)
    replacement_pool = _FakePool()
    monkeypatch.setattr(postgres_dal, "_pool", closed_pool)
    monkeypatch.setattr(postgres_dal, "_create_pool", lambda: replacement_pool)

    assert postgres_dal.get_pool() is replacement_pool
    assert postgres_dal.get_pool() is replacement_pool
