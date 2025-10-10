import datetime as dt
import importlib
from unittest import mock

import pytest


@pytest.fixture()
def generate_plan_module():
    module = importlib.import_module("scripts.generate_plan")
    return module


def test_generate_plan_cli_invokes_service(monkeypatch, generate_plan_module):
    mock_service = mock.Mock()
    monkeypatch.setattr(generate_plan_module, "PlanGenerationService", mock.Mock(return_value=mock_service))
    monkeypatch.setattr("sys.argv", ["generate_plan", "--start-date", "2025-10-27", "--dry-run"])

    generate_plan_module.main()

    mock_service.run.assert_called_once_with(start_date=dt.date(2025, 10, 27), dry_run=True)
