"""Provide a minimal pete_e.config stub for tests."""
from __future__ import annotations

import os
import sys
import types
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

try:
    from psycopg.conninfo import make_conninfo
except ImportError:  # pragma: no cover - psycopg not installed in some envs
    make_conninfo = None  # type: ignore


if "pete_e.config" in sys.modules:
    config_module = sys.modules["pete_e.config"]
else:
    config_module = types.ModuleType("pete_e.config")
    sys.modules["pete_e.config"] = config_module


T = TypeVar("T")


class Settings:
    """Light-weight stand in for the production Settings class used in tests."""

    def __init__(self, **overrides: Any) -> None:
        defaults: dict[str, Any] = {
            "USER_DATE_OF_BIRTH": date(1990, 1, 1),
            "USER_HEIGHT_CM": 175,
            "USER_GOAL_WEIGHT_KG": 75.0,
            "TELEGRAM_TOKEN": "telegram-token",
            "TELEGRAM_CHAT_ID": "chat-id",
            "WITHINGS_CLIENT_ID": "withings-client-id",
            "WITHINGS_CLIENT_SECRET": "withings-client-secret",
            "WITHINGS_REDIRECT_URI": "https://example.com/redirect",
            "WITHINGS_REFRESH_TOKEN": "withings-refresh-token",
            "WGER_API_KEY": "wger-api-key",
            "WGER_BASE_URL": "https://example.com/api/v2",
            "DROPBOX_HEALTH_METRICS_DIR": "health",
            "DROPBOX_WORKOUTS_DIR": "workouts",
            "DROPBOX_APP_KEY": "dropbox-app-key",
            "DROPBOX_APP_SECRET": "dropbox-app-secret",
            "DROPBOX_REFRESH_TOKEN": "dropbox-refresh-token",
            "POSTGRES_USER": "postgres-user",
            "POSTGRES_PASSWORD": "postgres-password",
            "POSTGRES_HOST": "postgres-host",
            "POSTGRES_PORT": 5432,
            "POSTGRES_DB": "postgres-db",
            "BASELINE_DAYS": 14,
            "PROGRESSION_INCREMENT": 0.05,
            "PROGRESSION_DECREMENT": 0.05,
            "RHR_ALLOWED_INCREASE": 0.10,
            "SLEEP_ALLOWED_DECREASE": 0.85,
            "HRV_ALLOWED_DECREASE": 0.12,
            "BODY_AGE_ALLOWED_INCREASE": 2.0,
            "GLOBAL_BACKOFF_FACTOR": 0.90,
            "CYCLE_DAYS": 28,
            "PETE_LOG_LEVEL": "INFO",
            "PETE_LOG_FORMAT": "json",
            "PETE_LOG_TO_CONSOLE": True,
            "PETEEEBOT_COMMAND_RATE_LIMIT_MAX_REQUESTS": 10,
            "PETEEEBOT_COMMAND_RATE_LIMIT_WINDOW_SECONDS": 60.0,
            "PETEEEBOT_SYNC_TIMEOUT_SECONDS": 300.0,
            "PETEEEBOT_PROCESS_TIMEOUT_SECONDS": 900.0,
            "WGER_EXPAND_STRETCH_ROUTINES": False,
        }
        defaults.update(overrides)

        for key, value in defaults.items():
            setattr(self, key, value)

        self.DATABASE_URL: Optional[str] = None
        self.build_database_url()
        """Initialize this object."""

    def build_database_url(self) -> "Settings":
        host_override = os.getenv("DB_HOST_OVERRIDE", self.POSTGRES_HOST)
        params = {
            "user": self.POSTGRES_USER,
            "password": self.POSTGRES_PASSWORD,
            "host": host_override,
            "port": self.POSTGRES_PORT,
            "dbname": self.POSTGRES_DB,
        }
        if make_conninfo is not None:
            self.DATABASE_URL = make_conninfo(**params)
        else:  # pragma: no cover - fallback for minimal environments
            self.DATABASE_URL = " ".join(f"{k}={v}" for k, v in params.items())
        return self
        """Perform build database url."""

    @property
    def log_path(self) -> Path:  # pragma: no cover - trivial property
        resolved_path, _notice = self._resolve_log_path()
        return resolved_path
        """Perform log path."""

    def consume_log_path_notice(self) -> str | None:
        _resolved_path, notice = self._resolve_log_path()
        if not notice:
            return None
        if getattr(self, "_log_path_notice_consumed", False):
            return None
        self._log_path_notice_consumed = True
        return notice
        """Perform consume log path notice."""

    def _resolve_log_path(self) -> tuple[Path, str | None]:
        return Path("logs/test.log"), None
        """Perform resolve log path."""

    @property
    def phrases_path(self) -> Path:
        return Path("pete_e/resources/phrases_tagged.json")
        """Perform phrases path."""


def get_env(
    name: str,
    default: T | None = None,
    *,
    parser: Callable[[str], T] | None = None,
) -> T | Any | None:
    if name in os.environ:
        raw_value = os.environ[name]
        return parser(raw_value) if parser else raw_value
    if hasattr(config_module.settings, name):
        return getattr(config_module.settings, name)
    return default
    """Perform get env."""


# expose Settings and a default instance
config_module.Settings = Settings
config_module.settings = Settings()
config_module.get_env = get_env

config_submodule = types.ModuleType("pete_e.config.config")
config_submodule.Settings = Settings
config_submodule.settings = config_module.settings
config_submodule.get_env = get_env
sys.modules["pete_e.config.config"] = config_submodule
