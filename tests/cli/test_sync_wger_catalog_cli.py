import importlib
from unittest import mock

import pytest


@pytest.fixture()
def sync_module():
    return importlib.import_module("scripts.sync_wger_catalog")


def test_catalog_sync_cli_invokes_service(monkeypatch, sync_module):
    mock_service = mock.Mock()
    monkeypatch.setattr(sync_module, "CatalogSyncService", mock.Mock(return_value=mock_service))
    monkeypatch.setattr("sys.argv", ["sync_wger_catalog"])

    sync_module.main()

    mock_service.run.assert_called_once_with()
