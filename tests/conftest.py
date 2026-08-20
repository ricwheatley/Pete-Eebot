"""Shared pytest policy for deterministic, real-dependency test runs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ISOLATED_ENV_FILE = ROOT / ".pytest-no-env"

# Test collection imports modules that construct the settings singleton. Set a
# complete, unmistakably non-production environment before those imports and
# point Pydantic Settings away from the developer's repository-local ``.env``.
_TEST_ENV = {
    "ENVIRONMENT": "testing",
    "PETEEEBOT_ENV_FILE": str(ISOLATED_ENV_FILE),
    "USER_DATE_OF_BIRTH": "1990-01-01",
    "USER_HEIGHT_CM": "180",
    "USER_GOAL_WEIGHT_KG": "80",
    "TELEGRAM_TOKEN": "test-telegram-token",
    "TELEGRAM_CHAT_ID": "123456",
    "WITHINGS_CLIENT_ID": "",
    "WITHINGS_CLIENT_SECRET": "",
    "WITHINGS_REDIRECT_URI": "",
    "WITHINGS_REFRESH_TOKEN": "",
    "WGER_API_KEY": "test-wger-key",
    "DROPBOX_HEALTH_METRICS_DIR": "/health",
    "DROPBOX_WORKOUTS_DIR": "/workouts",
    "DROPBOX_APP_KEY": "",
    "DROPBOX_APP_SECRET": "",
    "DROPBOX_REFRESH_TOKEN": "",
    "APPLE_MAX_STALE_DAYS": "3",
    "WITHINGS_ALERT_REAUTH": "true",
    "POSTGRES_USER": "pete_test",
    "POSTGRES_PASSWORD": "pete_test",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "1",
    "POSTGRES_DB": "pete_e_test_unreachable",
    "DATABASE_URL": (
        "postgresql://pete_test:pete_test@127.0.0.1:1/"
        "pete_e_test_unreachable?connect_timeout=1"
    ),
    "PETEEEBOT_API_KEY": "test-api-key",
    "PETE_LOG_TO_CONSOLE": "false",
}
os.environ.update(_TEST_ENV)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the explicit opt-in for destructive disposable-DB setup."""

    parser.addoption(
        "--run-postgres",
        action="store_true",
        default=False,
        help="run PostgreSQL integration tests against PETEEEBOT_TEST_DATABASE_URL",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify all otherwise-unmarked tests into the fast unit lane."""

    lane_names = {"unit", "contract", "integration", "artifact"}
    for item in items:
        if not any(item.get_closest_marker(name) is not None for name in lane_names):
            item.add_marker(pytest.mark.unit)
