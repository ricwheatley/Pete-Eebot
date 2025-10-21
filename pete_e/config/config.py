"""
Centralised config for the entire application.

This module consolidates all configuration settings, loading sensitive values
from environment variables and providing typed, validated access to them
through a singleton `settings` object.
"""

import os
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_FILE = Path(__file__).resolve()


def _discover_project_root(config_file: Path) -> tuple[Path, Path]:
    """Return a project root and env file path without assuming ``.env`` exists.

    The production deployment stores a ``.env`` file alongside the repository,
    but that file is intentionally absent in development and CI.  The previous
    implementation relied on ``next(...)`` to find the first parent directory
    containing ``.env`` which raised ``StopIteration`` during tests.  Instead we
    walk the parents looking for a ``.env`` file and gracefully fall back to the
    repository root (detected via common project markers) when it is missing.
    """

    parents = list(config_file.parents)

    for parent in parents:
        env_file = parent / ".env"
        if env_file.exists():
            return parent, env_file

    # Fall back to a sensible default if no .env is present.
    for marker in ("pyproject.toml", ".git", "requirements.txt"):
        for parent in parents:
            if (parent / marker).exists():
                return parent, parent / ".env"

    # As a last resort, pick the immediate package parent.
    fallback_root = parents[1] if len(parents) > 1 else parents[0]
    return fallback_root, fallback_root / ".env"


PROJECT_ROOT, ENV_FILE_PATH = _discover_project_root(CONFIG_FILE)


def _discover_app_root(project_root: Path) -> Path:
    """Resolve the root used for locating bundled application resources."""

    for candidate in (project_root / "app", project_root):
        if (candidate / "pete_e").exists():
            return candidate
    return project_root


APP_ROOT = _discover_app_root(PROJECT_ROOT)


T = TypeVar("T")



class Settings(BaseSettings):
    """
    Centralised and validated application settings.
    """
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH, env_file_encoding="utf-8", case_sensitive=False
    )
    ##print(f"Loading environment from: {ENV_FILE_PATH}")
    # --- CORE APP SETTINGS ---
    PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
    ENVIRONMENT: str = "development"
    DATABASE_URL: Optional[str] = Field(None, validate_default=True)

    # --- USER PROFILE (from environment) ---
    USER_DATE_OF_BIRTH: date
    USER_HEIGHT_CM: int
    USER_GOAL_WEIGHT_KG: float

    # --- API CREDENTIALS (from environment) ---
    TELEGRAM_TOKEN: SecretStr
    TELEGRAM_CHAT_ID: str
    WITHINGS_CLIENT_ID: str
    WITHINGS_CLIENT_SECRET: SecretStr
    WITHINGS_REDIRECT_URI: str
    WITHINGS_REFRESH_TOKEN: SecretStr
    WGER_API_KEY: SecretStr
    WGER_BASE_URL: str = "https://wger.de/api/v2"
    WGER_USERNAME: str | None = None
    WGER_PASSWORD: str | None = None
    
    # --- DROPBOX (from environment) ---
    DROPBOX_HEALTH_METRICS_DIR: str
    DROPBOX_WORKOUTS_DIR: str
    DROPBOX_APP_KEY: str
    DROPBOX_APP_SECRET: str
    DROPBOX_REFRESH_TOKEN: str

    # --- API KEYS (from environment) ---
    PETEEEBOT_API_KEY: str | None = None
    PETE_LOG_LEVEL: str = "INFO"
    PETE_LOG_TO_CONSOLE: bool = True 


    # --- SANITY CHECK ALERTS ---
    APPLE_MAX_STALE_DAYS: int = 3
    WITHINGS_ALERT_REAUTH: bool = True

    # --- DATABASE CONNECTION (from environment) ---
    POSTGRES_USER: str
    POSTGRES_PASSWORD: SecretStr
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str

    # --- PROGRESSION & RECOVERY THRESHOLDS ---
    PROGRESSION_INCREMENT: float = 0.05
    PROGRESSION_DECREMENT: float = 0.05
    RHR_ALLOWED_INCREASE: float = 0.10
    SLEEP_ALLOWED_DECREASE: float = 0.85
    HRV_ALLOWED_DECREASE: float = 0.12
    BODY_AGE_ALLOWED_INCREASE: float = 2.0
    GLOBAL_BACKOFF_FACTOR: float = 0.90

    # --- METRIC WINDOWS ---
    BASELINE_DAYS: int = 28
    CYCLE_DAYS: int = 28

    # --- PLAN BUILDER RECOVERY THRESHOLDS ---
    RECOVERY_SLEEP_THRESHOLD_MINUTES: int = 420
    RECOVERY_RHR_THRESHOLD: int = 60
    VO2_HIGH_THRESHOLD: float = 48.0
    VO2_LOW_THRESHOLD: float = 36.0

    # --- WGER EXPORT CONTROLS ---
    WGER_DRY_RUN: bool = False
    WGER_FORCE_OVERWRITE: bool = False
    WGER_EXPORT_DEBUG: bool = False
    WGER_BLAZE_MODE: str = "exercise"
    WGER_ROUTINE_PREFIX: str | None = None

    @model_validator(mode="after")
    def build_database_url(self) -> "Settings":
        """Dynamically construct the ``DATABASE_URL`` after validation."""
        db_host = os.getenv("DB_HOST_OVERRIDE", self.POSTGRES_HOST)
        conninfo_params = {
            "user": self.POSTGRES_USER,
            "password": self.POSTGRES_PASSWORD.get_secret_value(),
            "host": db_host,
            "port": self.POSTGRES_PORT,
            "dbname": self.POSTGRES_DB,
        }

        self.DATABASE_URL = _build_conninfo(conninfo_params)
        return self

    # --- DYNAMIC FILE PATHS ---
    @property
    def log_path(self) -> Path:
        """
        Path for the main application log file.
    
        This version is fail-safe: if /var/log/pete_eebot is not writable,
        it falls back to a local user directory and never raises exceptions.
        """
        try:
            prod_log_dir = Path("/var/log/pete_eebot")
            if prod_log_dir.exists() and os.access(prod_log_dir, os.W_OK):
                return prod_log_dir / "pete_history.log"
            else:
                raise PermissionError("No access to /var/log/pete_eebot")
        except Exception as e:
            fallback_dir = Path.home() / "pete_logs"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            fallback_path = fallback_dir / "pete_history.log"
            print(f"[Pete-Eebot] ⚠️ Falling back to {fallback_path} due to: {e}")
            return fallback_path

    @property
    def phrases_path(self) -> Path:
        """Path to the tagged phrases resource file."""
        return APP_ROOT / "pete_e/resources/phrases_tagged.json"


def _build_conninfo(params: dict[str, Any]) -> str:
    """Return a libpq-compatible connection string from keyword parameters."""

    try:
        from psycopg.conninfo import make_conninfo as _make_conninfo  # type: ignore

        return _make_conninfo(**params)
    except ModuleNotFoundError:
        pass

    def _quote(value: Any) -> str:
        text = str(value)
        if not text:
            return "''"
        if any(ch.isspace() for ch in text) or any(ch in "'\\" for ch in text):
            escaped = text.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"
        return text

    return " ".join(f"{key}={_quote(value)}" for key, value in params.items())


# Create a single, importable instance of the settings for the entire application.
settings = Settings()


def _coerce_secret(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


def _to_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _coerce_type(raw: str, template: Any) -> Any:
    if isinstance(template, bool):
        return _to_bool(raw)
    if isinstance(template, int) and not isinstance(template, bool):
        return int(raw)
    if isinstance(template, float):
        return float(raw)
    if isinstance(template, Path):
        return Path(raw)
    return raw


def get_env(
    name: str,
    default: T | None = None,
    *,
    parser: Callable[[str], T] | None = None,
) -> T | Any | None:
    """Return a configuration value resolving environment overrides consistently.

    The resolution order is:

    1. Explicit environment variable overrides at runtime.
    2. Typed values provided by the Pydantic ``settings`` object.
    3. The supplied ``default`` value.

    When an override is read directly from :mod:`os.environ`, ``parser`` (or the
    inferred type from ``settings``) is used to coerce the string into the
    expected type.
    """

    if name in os.environ:
        raw_value = os.environ[name]
        if parser is not None:
            return parser(raw_value)
        if hasattr(settings, name):
            template = _coerce_secret(getattr(settings, name))
            try:
                return _coerce_type(raw_value, template)
            except (TypeError, ValueError):
                return template
        return raw_value

    if hasattr(settings, name):
        return _coerce_secret(getattr(settings, name))

    return default


