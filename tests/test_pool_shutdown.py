import pytest
from unittest.mock import MagicMock

# Import the modules we need to test and mock
from pete_e.application import orchestrator as orchestrator_module
from pete_e.application.orchestrator import Orchestrator
from pete_e.application.sync import run_sync_with_retries, SyncResult


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
    orchestrator = Orchestrator(
        dal=mock_dal,
        wger_client=mock_wger_client,
        plan_service=mock_plan_service,
        export_service=mock_export_service,
    )

    # Call the method we want to test
    orchestrator.close()

    # Assert that the DAL's close method was called exactly once
    mock_dal.close.assert_called_once()


def test_run_sync_with_retries_closes_orchestrator_and_pool(monkeypatch):
    """
    Tests that the main sync function properly closes the orchestrator's resources
    (and thus the connection pool) after execution, both on success and failure.
    """
    close_calls = []

    # Stub the Orchestrator to control its behavior
    class StubOrchestrator:
        def __init__(self):
            # This flag will let us simulate a failure
            self.should_fail = False

        def run_daily_sync(self, days):
            if self.should_fail:
                raise RuntimeError("Simulated sync failure")
            # Return a successful result tuple
            return True, [], {}, []

        def close(self):
            # Record when the close method is called
            close_calls.append("closed")

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