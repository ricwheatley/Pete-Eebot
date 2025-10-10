#!/usr/bin/env python3
"""CLI entrypoint for refreshing the local wger catalog."""

from pete_e.application.catalog_sync import CatalogSyncService


def main() -> None:
    CatalogSyncService().run()


if __name__ == "__main__":
    main()
