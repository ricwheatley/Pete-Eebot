"""
Centralised config for the entire application.

This module consolidates all configuration settings, loading sensitive values
from environment variables and providing typed, validated access to them
through a singleton `settings` object.
"""

import os
from datetime import date
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import quote

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from psycopg.conninfo import conninfo_to_dict

CONFIG_FILE = Path(__file__).resolve()


def _explicit_env_file() -> Path | None:
    """Return an explicitly configured env file path when one is provided."""

    raw_path = os.getenv("PETEEEBOT_ENV_FILE")
    if not raw_path:
        return None
    return Path(raw_path).expanduser()


def _discover_project_root(config_file: Path) -> tuple[Path, Path]:
    """Return a project root and env file path without assuming ``.env`` exists."""

    explicit_env_file = _explicit_env_file()
    parents = list(config_file.parents)

    if explicit_env_file is not None:
        for marker in ("pyproject.toml", ".git", "requirements.txt"):
            for parent in parents:
                if (parent / marker).exists():
                    return parent, explicit_env_file
        fallback_root = parents[1] if len(parents) > 1 else parents[0]
        return fallback_root, explicit_env_file

    for parent in parents:
        env_file = parent / ".env"
        if env_file.exists():
            return parent, env_file

    for marker in ("pyproject.toml", ".git", "requirements.txt"):
        for parent in parents:
            if (parent / marker).exists():
                return parent, parent / ".env"

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
    """Centralised and validated application settings."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )

    # --- CORE APP SETTINGS ---
    PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
    PETEEEBOT_ENV_FILE: Path | None = None
    ENVIRONMENT: str = "development"
    DATABASE_URL: SecretStr | None = Field(None, validate_default=True)
    PETEEEBOT_MIGRATOR_DATABASE_URL: SecretStr | None = None

    # --- USER PROFILE (from environment) ---
    USER_DATE_OF_BIRTH: date
    USER_HEIGHT_CM: int
    USER_GOAL_WEIGHT_KG: float
    USER_TIMEZONE: str = "Europe/London"
    PETEEEBOT_DEFAULT_PROFILE_SLUG: str = "default"
    PETEEEBOT_DEFAULT_PROFILE_NAME: str | None = None

    # --- API CREDENTIALS (from environment) ---
    TELEGRAM_TOKEN: SecretStr
    TELEGRAM_CHAT_ID: str
    WITHINGS_CLIENT_ID: str
    WITHINGS_CLIENT_SECRET: SecretStr
    WITHINGS_REDIRECT_URI: str
    WITHINGS_REFRESH_TOKEN: SecretStr
    WITHINGS_TOKEN_FILE: Path | None = None
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
    DROPBOX_BACKUP_DIR: str = "/Pete-Eebot Backups"
    DROPBOX_BACKUP_TIMEOUT: float = 60.0

    # --- DUCKDNS ---
    DUCKDNS_DOMAIN: str | None = None
    DUCKDNS_TOKEN: SecretStr | None = None

    # --- BACKUPS ---
    BACKUP_ROOT: Path | None = None
    DB_BACKUP_DIR: Path | None = None
    SECRETS_BACKUP_DIR: Path | None = None
    CLOUD_STAGING_DIR: Path | None = None
    BACKUP_CLOUD_UPLOAD: bool = False
    BACKUP_ENCRYPTION_KEY_FILE: Path | None = None
    BACKUP_ENCRYPTION_PASSPHRASE: SecretStr | None = None
    RETENTION_WEEKS: int = 8

    # --- SERVICE WATCHDOG ---
    PETEEEBOT_SERVICE_NAME: str = "peteeebot.service"
    PETEEEBOT_RESTART_TIMEOUT_SECONDS: float = 60.0
    PETEEEBOT_SERVICE_MONITOR_LOG: Path = Path("/var/log/pete_eebot/service_monitor.log")
    SYSTEMCTL_BIN: str = "/bin/systemctl"
    SUDO_BIN: str = "sudo"

    # --- API KEYS (from environment) ---
    PETEEEBOT_API_KEY: str | None = None
    PETEEEBOT_SESSION_COOKIE_NAME: str = "peteeebot_session"
    PETEEEBOT_CSRF_COOKIE_NAME: str = "peteeebot_csrf"
    PETEEEBOT_SESSION_COOKIE_DOMAIN: str | None = None
    PETEEEBOT_SESSION_COOKIE_SECURE: bool | None = None
    PETEEEBOT_SESSION_COOKIE_SAMESITE: str = "lax"
    PETEEEBOT_CORS_ALLOWED_ORIGINS: str = ""
    PETEEEBOT_ENABLE_HSTS: bool | None = None
    PETEEEBOT_TRUSTED_PROXY_CIDRS: str = ""
    PETEEEBOT_LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = 5
    PETEEEBOT_LOGIN_RATE_LIMIT_WINDOW_SECONDS: float = 300.0
    PETEEEBOT_LOGIN_LOCKOUT_SECONDS: float = 900.0
    PETEEEBOT_LOGIN_BACKOFF_BASE_SECONDS: float = 1.0
    GITHUB_WEBHOOK_SECRET: SecretStr | None = None
    PETEEEBOT_GITHUB_REPOSITORY_ID: int | None = None
    PETEEEBOT_GITHUB_DEPLOY_REF: str = "refs/heads/main"
    PETEEEBOT_WEBHOOK_MAX_BODY_BYTES: int = Field(262_144, ge=1_024, le=10_485_760)
    DEPLOY_SCRIPT_PATH: Path | None = None
    PETEEEBOT_DEPLOY_GIT_REMOTE: str = "origin"
    PETEEEBOT_DEPLOY_GIT_REMOTE_URL: str | None = None
    PETEEEBOT_DEPLOY_UNIT_TEMPLATE: str = "peteeebot-deploy@.service"
    PETEEEBOT_DEPLOY_DISPATCH_BIN: Path = Path("/usr/local/sbin/peteeebot-dispatch-deploy")
    PETEEEBOT_DEPLOY_DISPATCH_TIMEOUT_SECONDS: float = Field(30.0, ge=1, le=120)
    PETEEEBOT_CLI_BIN: Path | str | None = None
    PETEEEBOT_COMMAND_RATE_LIMIT_MAX_REQUESTS: int = 10
    PETEEEBOT_COMMAND_RATE_LIMIT_WINDOW_SECONDS: float = 60.0
    PETEEEBOT_COMMAND_RATE_LIMIT_GLOBAL_MULTIPLIER: int = Field(5, ge=1, le=100)
    PETEEEBOT_DEEP_STATUS_CACHE_SECONDS: float = Field(30.0, ge=0, le=300)
    PETEEEBOT_SYNC_TIMEOUT_SECONDS: float = 300.0
    PETEEEBOT_PROCESS_TIMEOUT_SECONDS: float = 900.0
    PETEEEBOT_JOB_LEASE_SECONDS: float = Field(300.0, ge=5, le=3600)
    PETEEEBOT_JOB_HEARTBEAT_SECONDS: float = Field(60.0, ge=1, le=1200)
    PETEEEBOT_JOB_RECOVERY_SECONDS: float = Field(60.0, ge=1, le=1200)
    PETE_LOG_LEVEL: str = "INFO"
    PETE_LOG_FORMAT: str = "json"
    PETE_LOG_TO_CONSOLE: bool = True
    PETEEEBOT_LLM_ENABLED: bool = False
    PETEEEBOT_LLM_BASE_URL: str = "http://127.0.0.1:11434"
    PETEEEBOT_LLM_MODEL: str = "qwen2.5:1.5b"
    PETEEEBOT_LLM_TIMEOUT_SECONDS: float = 30.0
    PETEEEBOT_LLM_KEEP_ALIVE: str = "30m"

    # --- SANITY CHECK ALERTS ---
    APPLE_MAX_STALE_DAYS: int = Field(3, ge=1)
    WITHINGS_ALERT_REAUTH: bool = True
    PETEEEBOT_ALERT_TELEGRAM_ENABLED: bool = True
    PETEEEBOT_ALERT_DEDUPE_SECONDS: float = Field(3600.0, ge=0, allow_inf_nan=False)
    PETEEEBOT_STALE_INGEST_ALERT_DAYS: int = Field(3, ge=1)
    PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD: int = Field(3, ge=0)

    # --- DATABASE CONNECTION (from environment) ---
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: SecretStr | None = None
    POSTGRES_HOST: str | None = None
    POSTGRES_PORT: int = Field(5432, ge=1, le=65535)
    POSTGRES_DB: str | None = None
    DB_HOST_OVERRIDE: str | None = None

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
    ASSISTANCE_MAX_DIFFICULTY: int = 5
    RECOVERY_SLEEP_THRESHOLD_MINUTES: int = 420
    RECOVERY_RHR_THRESHOLD: int = 60
    VO2_HIGH_THRESHOLD: float = 48.0
    VO2_LOW_THRESHOLD: float = 36.0

    # --- RUNNING GOAL ---
    RUNNING_TARGET_RACE: str | None = "marathon"
    RUNNING_RACE_DATE: date | None = date(2027, 4, 18)
    RUNNING_TARGET_TIME: str | None = None
    RUNNING_WEIGHT_LOSS_TARGET_KG: float | None = 22.0

    # --- WGER EXPORT CONTROLS ---
    WGER_DRY_RUN: bool = False
    WGER_FORCE_OVERWRITE: bool = False
    WGER_EXPORT_DEBUG: bool = False
    WGER_BLAZE_MODE: str = "exercise"
    WGER_ROUTINE_PREFIX: str | None = None
    WGER_TIMEOUT: float = 30.0
    WGER_MAX_RETRIES: int = 3
    WGER_BACKOFF_BASE: float = 1.0
    WGER_EXPAND_STRETCH_ROUTINES: bool = False
    PETEEEBOT_PLANNER_FEATURE_FLAGS: str = ""

    @model_validator(mode="after")
    def preserve_legacy_stale_alert_threshold(self) -> "Settings":
        """Use the legacy Apple threshold when the new alert setting is absent."""

        if (
            "PETEEEBOT_STALE_INGEST_ALERT_DAYS" not in self.model_fields_set
            and "APPLE_MAX_STALE_DAYS" in self.model_fields_set
        ):
            self.PETEEEBOT_STALE_INGEST_ALERT_DAYS = self.APPLE_MAX_STALE_DAYS
        return self

    @model_validator(mode="after")
    def validate_job_lease_cadence(self) -> "Settings":
        """Require enough heartbeat margin to fence work before lease expiry."""

        if self.PETEEEBOT_JOB_HEARTBEAT_SECONDS >= self.PETEEEBOT_JOB_LEASE_SECONDS / 2:
            raise ValueError(
                "PETEEEBOT_JOB_HEARTBEAT_SECONDS must be less than half "
                "PETEEEBOT_JOB_LEASE_SECONDS"
            )
        if self.PETEEEBOT_JOB_RECOVERY_SECONDS > self.PETEEEBOT_JOB_LEASE_SECONDS:
            raise ValueError(
                "PETEEEBOT_JOB_RECOVERY_SECONDS must not exceed "
                "PETEEEBOT_JOB_LEASE_SECONDS"
            )
        return self

    @model_validator(mode="after")
    def resolve_database_url(self) -> "Settings":
        """Resolve one authoritative database connection string."""

        explicit_url = _secret_value(self.DATABASE_URL)
        if explicit_url is not None:
            explicit_url = explicit_url.strip()
        if not explicit_url:
            explicit_url = None

        component_names = {
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "DB_HOST_OVERRIDE",
        }
        supplied_components = component_names.intersection(self.model_fields_set)
        missing_components = _missing_database_components(self)

        if explicit_url is not None:
            explicit_params = _parse_database_connection_string(explicit_url)
            if supplied_components:
                if missing_components:
                    missing = ", ".join(missing_components)
                    raise ValueError(
                        "DATABASE_URL was provided with a partial POSTGRES_* configuration. "
                        "Remove all component values or provide the complete matching set; "
                        f"missing: {missing}."
                    )
                component_url = _build_database_url(self)
                component_params = _parse_database_connection_string(component_url)
                conflicts = _database_component_conflicts(explicit_params, component_params)
                if conflicts:
                    names = ", ".join(conflicts)
                    raise ValueError(
                        "DATABASE_URL conflicts with the supplied PostgreSQL components: "
                        f"{names}. Remove one source or make them match."
                    )
            self.DATABASE_URL = SecretStr(explicit_url)
            return self

        if missing_components:
            missing = ", ".join(missing_components)
            raise ValueError(
                "Database configuration is incomplete. Set DATABASE_URL by itself, or "
                "provide POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, and POSTGRES_DB; "
                f"missing: {missing}."
            )

        self.DATABASE_URL = SecretStr(_build_database_url(self))
        return self

    # --- DYNAMIC FILE PATHS ---
    @property
    def log_path(self) -> Path:
        """Return the resolved application log path without writing to stdout."""

        resolved_path, _notice = self._resolve_log_path()
        return resolved_path

    def consume_log_path_notice(self) -> str | None:
        """Return any one-time log-path fallback notice."""

        _resolved_path, notice = self._resolve_log_path()
        if not notice:
            return None
        if self.__dict__.get("_log_path_notice_consumed"):
            return None
        self.__dict__["_log_path_notice_consumed"] = True
        return notice

    def _resolve_log_path(self) -> tuple[Path, str | None]:
        cached = self.__dict__.get("_resolved_log_path")
        if cached is not None:
            return cached

        prod_log_dir = Path("/var/log/pete_eebot")
        if prod_log_dir.exists() and os.access(prod_log_dir, os.W_OK):
            resolved = (prod_log_dir / "pete_history.log", None)
        else:
            fallback_dir = Path.home() / "pete_logs"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            fallback_path = fallback_dir / "pete_history.log"
            resolved = (
                fallback_path,
                f"Falling back to {fallback_path} because /var/log/pete_eebot is unavailable.",
            )

        self.__dict__["_resolved_log_path"] = resolved
        return resolved
        """Perform resolve log path."""

    @property
    def phrases_path(self) -> Path:
        """Path to the tagged phrases resource file."""

        return APP_ROOT / "pete_e/resources/phrases_tagged.json"


def _secret_value(value: SecretStr | str | None) -> str | None:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


def _missing_database_components(settings_value: Settings) -> list[str]:
    values = {
        "POSTGRES_USER": settings_value.POSTGRES_USER,
        "POSTGRES_PASSWORD": _secret_value(settings_value.POSTGRES_PASSWORD),
        "POSTGRES_HOST": settings_value.POSTGRES_HOST,
        "POSTGRES_DB": settings_value.POSTGRES_DB,
    }
    return [name for name, value in values.items() if value is None or value == ""]


def _build_database_url(settings_value: Settings) -> str:
    """Build a percent-encoded PostgreSQL URI from validated components."""

    user = quote(str(settings_value.POSTGRES_USER), safe="")
    password = quote(str(_secret_value(settings_value.POSTGRES_PASSWORD)), safe="")
    host_value = settings_value.DB_HOST_OVERRIDE or settings_value.POSTGRES_HOST
    host = _encode_database_host(str(host_value))
    database = quote(str(settings_value.POSTGRES_DB), safe="")
    return f"postgresql://{user}:{password}@{host}:{settings_value.POSTGRES_PORT}/{database}"


def _encode_database_host(host: str) -> str:
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if ":" in host:
        return f"[{quote(host, safe=':')}]"
    return quote(host, safe="")


def _parse_database_connection_string(connection_string: str) -> dict[str, str]:
    try:
        return conninfo_to_dict(connection_string)
    except Exception as exc:
        raise ValueError(
            "DATABASE_URL is not a valid PostgreSQL connection string."
        ) from exc


def _database_component_conflicts(
    explicit_params: dict[str, str],
    component_params: dict[str, str],
) -> list[str]:
    field_names = {
        "user": "POSTGRES_USER",
        "password": "POSTGRES_PASSWORD",
        "host": "POSTGRES_HOST/DB_HOST_OVERRIDE",
        "port": "POSTGRES_PORT",
        "dbname": "POSTGRES_DB",
    }
    conflicts: list[str] = []
    for parameter, field_name in field_names.items():
        explicit_value = explicit_params.get(parameter)
        component_value = component_params.get(parameter)
        if parameter == "port":
            explicit_value = explicit_value or "5432"
            component_value = component_value or "5432"
        if explicit_value != component_value:
            conflicts.append(field_name)
    return conflicts


settings = Settings()


def _coerce_secret(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value
    """Perform coerce secret."""


def _to_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    """Perform to bool."""


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
    """Perform coerce type."""


def get_env(
    name: str,
    default: T | None = None,
    *,
    parser: Callable[[str], T] | None = None,
) -> T | Any | None:
    """Return a configuration value resolving environment overrides consistently."""

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
