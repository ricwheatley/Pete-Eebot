#!/usr/bin/env python3
"""Compatibility wrapper for the canonical WGER catalogue sync service."""

from __future__ import annotations

import sys

from pete_e.application.catalog_sync import CatalogSyncService
from pete_e.infrastructure import log_utils


def run_wger_catalog_refresh() -> None:
    """Refresh the local WGER catalogue and Pete-owned programming metadata."""

    CatalogSyncService().run()


if __name__ == "__main__":
    try:
        run_wger_catalog_refresh()
    except (IOError, ValueError) as exc:
        log_utils.error(f"Catalogue refresh failed: {exc}")
        sys.exit(1)
