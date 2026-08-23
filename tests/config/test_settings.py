from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import re
import subprocess
import sys

import pydantic
import pydantic_settings
import pytest
from pydantic import ValidationError
from psycopg.conninfo import conninfo_to_dict

from pete_e.config.config import CONFIG_FILE, Settings, _discover_project_root
from pete_e.infrastructure import db_conn, postgres_dal


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PATH = ROOT / ".env.sample"
SAMPLE_KEY_PATTERN = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every Settings construction independent of developer/test-runner env."""

    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name, raising=False)
    monkeypatch.delenv("DB_HOST_OVERRIDE", raising=False)


@pytest.fixture()
def base_application_data() -> dict[str, object]:
    return {
        "USER_DATE_OF_BIRTH": date(1990, 1, 1),
        "USER_HEIGHT_CM": 180,
        "USER_GOAL_WEIGHT_KG": 80.0,
        "TELEGRAM_TOKEN": "sanitized-telegram-token",
        "TELEGRAM_CHAT_ID": "123456",
        "WITHINGS_CLIENT_ID": "sanitized-withings-client-id",
        "WITHINGS_CLIENT_SECRET": "sanitized-withings-client-secret",
        "WITHINGS_REDIRECT_URI": "https://example.invalid/redirect",
        "WITHINGS_REFRESH_TOKEN": "sanitized-withings-refresh-token",
        "WGER_API_KEY": "sanitized-wger-api-key",
        "DROPBOX_HEALTH_METRICS_DIR": "health",
        "DROPBOX_WORKOUTS_DIR": "workouts",
        "DROPBOX_APP_KEY": "sanitized-dropbox-app-key",
        "DROPBOX_APP_SECRET": "sanitized-dropbox-app-secret",
        "DROPBOX_REFRESH_TOKEN": "sanitized-dropbox-refresh-token",
    }


@pytest.fixture()
def component_data() -> dict[str, object]:
    return {
        "POSTGRES_USER": "postgres-user",
        "POSTGRES_PASSWORD": "postgres-password",
        "POSTGRES_HOST": "postgres-host",
        "POSTGRES_PORT": 5432,
        "POSTGRES_DB": "postgres-db",
    }


@pytest.fixture()
def base_settings_data(
    base_application_data: dict[str, object],
    component_data: dict[str, object],
) -> dict[str, object]:
    return {**base_application_data, **component_data}


def _database_url(settings_value: Settings) -> str:
    assert settings_value.DATABASE_URL is not None
    return settings_value.DATABASE_URL.get_secret_value()


def _write_env_file(path: Path, values: dict[str, object]) -> None:
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )


def _sanitized_sample_text() -> str:
    placeholder_values = {
        "USER_DATE_OF_BIRTH": "1990-01-01",
        "USER_HEIGHT_CM": "180",
        "USER_GOAL_WEIGHT_KG": "75",
        "TELEGRAM_CHAT_ID": "123456",
        "PETEEEBOT_LLM_ENABLED": "false",
        "PETEEEBOT_LLM_TIMEOUT_SECONDS": "30",
    }
    sanitized_lines: list[str] = []
    for line in SAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)=(.*)$", line)
        if match and "<" in match.group(2) and ">" in match.group(2):
            key = match.group(1)
            line = f"{key}={placeholder_values.get(key, 'sanitized-test-value')}"
        sanitized_lines.append(line)
    return "\n".join(sanitized_lines) + "\n"


def _subprocess_environment(env_file: Path) -> dict[str, str]:
    setting_names = {name.casefold() for name in Settings.model_fields}
    setting_names.add("db_host_override")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold() not in setting_names
    }
    environment["PETEEEBOT_ENV_FILE"] = str(env_file)
    return environment


def test_settings_use_installed_real_pydantic_packages() -> None:
    tests_dir = ROOT / "tests"
    for module in (pydantic, pydantic_settings):
        assert module.__file__ is not None
        assert tests_dir not in Path(module.__file__).resolve().parents


def test_every_documented_sample_key_is_a_declared_setting() -> None:
    sample_keys = set(SAMPLE_KEY_PATTERN.findall(SAMPLE_PATH.read_text(encoding="utf-8")))

    assert sample_keys <= set(Settings.model_fields)


def test_sanitized_documented_sample_loads_hermetically(tmp_path: Path) -> None:
    env_file = tmp_path / "sanitized-sample.env"
    env_file.write_text(_sanitized_sample_text(), encoding="utf-8")

    settings_value = Settings(_env_file=env_file)

    assert settings_value.USER_DATE_OF_BIRTH == date(1990, 1, 1)
    assert settings_value.PETEEEBOT_ALERT_TELEGRAM_ENABLED is True
    assert settings_value.PETEEEBOT_ALERT_DEDUPE_SECONDS == 3600.0
    assert settings_value.PETEEEBOT_STALE_INGEST_ALERT_DAYS == 3
    assert settings_value.PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD == 3
    assert conninfo_to_dict(_database_url(settings_value))["host"] == "127.0.0.1"


def test_sanitized_sample_supports_application_import_and_startup(tmp_path: Path) -> None:
    env_file = tmp_path / "sanitized-startup.env"
    env_file.write_text(_sanitized_sample_text(), encoding="utf-8")
    script = """
import asyncio
from pete_e.api import app

async def smoke():
    async with app.router.lifespan_context(app):
        assert app.openapi()["info"]["title"] == "Pete-Eebot API"

asyncio.run(smoke())
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=_subprocess_environment(env_file),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_initializer_process_env_dotenv_and_default_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    base_application_data: dict[str, object],
) -> None:
    env_file = tmp_path / "source-order.env"
    dotenv_url = "postgresql://dotenv-user:dotenv-password@dotenv-host:5432/dotenv-db"
    process_url = "postgresql://process-user:process-password@process-host:5432/process-db"
    initializer_url = "postgresql://init-user:init-password@init-host:5432/init-db"
    _write_env_file(
        env_file,
        {**base_application_data, "ENVIRONMENT": "dotenv", "DATABASE_URL": dotenv_url},
    )
    monkeypatch.setenv("ENVIRONMENT", "process")
    monkeypatch.setenv("DATABASE_URL", process_url)

    process_settings = Settings(_env_file=env_file)
    initializer_settings = Settings(
        _env_file=env_file,
        ENVIRONMENT="initializer",
        DATABASE_URL=initializer_url,
    )

    assert process_settings.ENVIRONMENT == "process"
    assert conninfo_to_dict(_database_url(process_settings))["host"] == "process-host"
    assert initializer_settings.ENVIRONMENT == "initializer"
    assert conninfo_to_dict(_database_url(initializer_settings))["host"] == "init-host"
    assert process_settings.WGER_BASE_URL == "https://wger.de/api/v2"


def test_process_component_override_cannot_silently_conflict_with_dotenv_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    base_settings_data: dict[str, object],
) -> None:
    env_file = tmp_path / "matching-dual.env"
    _write_env_file(
        env_file,
        {
            **base_settings_data,
            "DATABASE_URL": (
                "postgresql://postgres-user:postgres-password@postgres-host:5432/"
                "postgres-db"
            ),
        },
    )
    monkeypatch.setenv("POSTGRES_HOST", "ambient-host")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=env_file)

    assert "POSTGRES_HOST/DB_HOST_OVERRIDE" in str(exc_info.value)


def test_alert_defaults_and_zero_disable_semantics(base_application_data: dict[str, object]) -> None:
    settings_value = Settings(
        _env_file=None,
        **base_application_data,
        DATABASE_URL="postgresql://user:password@db.invalid:5432/database",
    )

    assert settings_value.PETEEEBOT_ALERT_TELEGRAM_ENABLED is True
    assert settings_value.PETEEEBOT_ALERT_DEDUPE_SECONDS == 3600.0
    assert settings_value.PETEEEBOT_STALE_INGEST_ALERT_DAYS == 3
    assert settings_value.PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD == 3

    disabled = Settings(
        _env_file=None,
        **base_application_data,
        DATABASE_URL="postgresql://user:password@db.invalid:5432/database",
        PETEEEBOT_ALERT_DEDUPE_SECONDS=0.0,
        PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD=0,
    )
    assert disabled.PETEEEBOT_ALERT_DEDUPE_SECONDS == 0.0
    assert disabled.PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD == 0


def test_legacy_stale_threshold_is_preserved_until_new_setting_is_supplied(
    base_application_data: dict[str, object],
) -> None:
    legacy_only = Settings(
        _env_file=None,
        **base_application_data,
        DATABASE_URL="postgresql://user:password@db.invalid:5432/database",
        APPLE_MAX_STALE_DAYS=6,
    )
    both = Settings(
        _env_file=None,
        **base_application_data,
        DATABASE_URL="postgresql://user:password@db.invalid:5432/database",
        APPLE_MAX_STALE_DAYS=6,
        PETEEEBOT_STALE_INGEST_ALERT_DAYS=4,
    )

    assert legacy_only.PETEEEBOT_STALE_INGEST_ALERT_DAYS == 6
    assert both.PETEEEBOT_STALE_INGEST_ALERT_DAYS == 4


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("PETEEEBOT_ALERT_DEDUPE_SECONDS", -0.01),
        ("PETEEEBOT_ALERT_DEDUPE_SECONDS", float("inf")),
        ("PETEEEBOT_STALE_INGEST_ALERT_DAYS", 0),
        ("PETEEEBOT_REPEATED_FAILURE_ALERT_THRESHOLD", -1),
    ],
)
def test_alert_bounds_are_validated(
    base_application_data: dict[str, object],
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            **base_application_data,
            DATABASE_URL="postgresql://user:password@db.invalid:5432/database",
            **{field_name: invalid_value},
        )


def test_explicit_database_url_only_is_authoritative(base_application_data: dict[str, object]) -> None:
    explicit_url = "postgresql://url-user:url-password@url-host:5440/url-db?sslmode=require"

    settings_value = Settings(
        _env_file=None,
        **base_application_data,
        DATABASE_URL=explicit_url,
    )

    assert _database_url(settings_value) == explicit_url
    assert settings_value.POSTGRES_USER is None


def test_component_only_database_configuration_builds_url(base_settings_data: dict[str, object]) -> None:
    settings_value = Settings(_env_file=None, **base_settings_data)

    parsed = conninfo_to_dict(_database_url(settings_value))
    assert parsed == {
        "user": "postgres-user",
        "password": "postgres-password",
        "dbname": "postgres-db",
        "host": "postgres-host",
        "port": "5432",
    }


def test_consistent_dual_database_configuration_preserves_explicit_url(
    base_settings_data: dict[str, object],
) -> None:
    explicit_url = (
        "postgresql://postgres-user:postgres-password@postgres-host:5432/"
        "postgres-db?connect_timeout=5&sslmode=require"
    )

    settings_value = Settings(
        _env_file=None,
        **base_settings_data,
        DATABASE_URL=explicit_url,
    )

    assert _database_url(settings_value) == explicit_url


def test_conflicting_dual_database_configuration_is_rejected_without_secret_leak(
    base_settings_data: dict[str, object],
) -> None:
    explicit_password = "explicit-private-password"
    component_password = "component-private-password"
    values = {
        **base_settings_data,
        "POSTGRES_PASSWORD": component_password,
        "DATABASE_URL": (
            f"postgresql://postgres-user:{explicit_password}@postgres-host:5432/postgres-db"
        ),
    }

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **values)

    message = str(exc_info.value)
    assert "POSTGRES_PASSWORD" in message
    assert explicit_password not in message
    assert component_password not in message


@pytest.mark.parametrize(
    "database_values",
    [
        {},
        {"POSTGRES_USER": "partial-user"},
        {
            "DATABASE_URL": "postgresql://url-user:url-password@url-host:5432/url-db",
            "POSTGRES_USER": "url-user",
        },
    ],
)
def test_missing_or_partial_database_configuration_fails_actionably(
    base_application_data: dict[str, object],
    database_values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **base_application_data, **database_values)

    message = str(exc_info.value)
    assert "Database" in message or "DATABASE_URL" in message
    assert "missing" in message


def test_invalid_explicit_database_url_fails_without_echoing_it(
    base_application_data: dict[str, object],
) -> None:
    invalid_url = "not-a-connection-string-with-private-password"

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **base_application_data, DATABASE_URL=invalid_url)

    message = str(exc_info.value)
    assert "not a valid PostgreSQL connection string" in message
    assert invalid_url not in message


def test_component_url_escapes_special_characters_and_redacts_password(
    base_application_data: dict[str, object],
) -> None:
    username = "user/name@example.invalid"
    password = "p@ss:/?#[]% word"
    database = "db/name with space"

    settings_value = Settings(
        _env_file=None,
        **base_application_data,
        POSTGRES_USER=username,
        POSTGRES_PASSWORD=password,
        POSTGRES_HOST="2001:db8::1",
        POSTGRES_DB=database,
    )

    database_url = _database_url(settings_value)
    parsed = conninfo_to_dict(database_url)
    assert parsed["user"] == username
    assert parsed["password"] == password
    assert parsed["host"] == "2001:db8::1"
    assert parsed["dbname"] == database
    assert "%2F" in database_url
    assert password not in repr(settings_value)
    assert password not in str(settings_value.DATABASE_URL)

    matching_dual = Settings(
        _env_file=None,
        **base_application_data,
        POSTGRES_USER=username,
        POSTGRES_PASSWORD=password,
        POSTGRES_HOST="2001:db8::1",
        POSTGRES_DB=database,
        DATABASE_URL=database_url,
    )
    assert _database_url(matching_dual) == database_url


def test_component_port_bounds_are_validated(base_settings_data: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **{**base_settings_data, "POSTGRES_PORT": 70000})

    assert "POSTGRES_PORT" in str(exc_info.value)


def test_declared_host_override_uses_normal_settings_precedence(
    base_settings_data: dict[str, object],
) -> None:
    settings_value = Settings(
        _env_file=None,
        **base_settings_data,
        DB_HOST_OVERRIDE="override-host",
    )

    assert conninfo_to_dict(_database_url(settings_value))["host"] == "override-host"


def test_resolved_database_url_reaches_connection_pool(
    monkeypatch: pytest.MonkeyPatch,
    base_application_data: dict[str, object],
) -> None:
    settings_value = Settings(
        _env_file=None,
        **base_application_data,
        DATABASE_URL="postgresql://pool-user:pool-password@pool-host:5432/pool-db",
    )
    captured: dict[str, object] = {}

    class CapturingPool:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(db_conn.settings, "DATABASE_URL", settings_value.DATABASE_URL)
    monkeypatch.setattr(postgres_dal, "ConnectionPool", CapturingPool)

    pool = postgres_dal._create_pool()

    assert isinstance(pool, CapturingPool)
    assert captured == {
        "conninfo": _database_url(settings_value),
        "min_size": 1,
        "max_size": 5,
    }


def test_unknown_dotenv_key_is_still_rejected(
    tmp_path: Path,
    base_application_data: dict[str, object],
) -> None:
    env_file = tmp_path / "unknown.env"
    _write_env_file(
        env_file,
        {
            **base_application_data,
            "DATABASE_URL": "postgresql://user:password@db.invalid:5432/database",
            "UNDOCUMENTED_SETTING": "value",
        },
    )

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=env_file)

    assert "extra_forbidden" in str(exc_info.value)


def test_explicit_env_file_does_not_replace_code_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / "shared" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("ENVIRONMENT=production\n", encoding="utf-8")

    monkeypatch.setenv("PETEEEBOT_ENV_FILE", str(env_file))
    project_root, discovered_env_file = _discover_project_root(CONFIG_FILE)

    assert discovered_env_file == env_file
    assert (project_root / "pete_e").exists()
    assert project_root != env_file.parent


def test_settings_reject_invalid_typed_value_from_isolated_env_file(
    tmp_path: Path,
    base_settings_data: dict[str, object],
) -> None:
    invalid_data = {**base_settings_data, "USER_HEIGHT_CM": "not-an-integer"}
    env_file = tmp_path / "invalid-settings.env"
    _write_env_file(env_file, invalid_data)

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)


def test_log_path_fallback_notice_is_consumed_once(
    monkeypatch: pytest.MonkeyPatch,
    base_settings_data: dict[str, object],
    tmp_path: Path,
) -> None:
    settings_value = Settings(_env_file=None, **base_settings_data)
    fallback_path = tmp_path / "pete_history.log"

    monkeypatch.setattr(
        Settings,
        "_resolve_log_path",
        lambda self: (fallback_path, "fallback notice"),
    )

    assert settings_value.log_path == fallback_path
    assert settings_value.consume_log_path_notice() == "fallback notice"
    assert settings_value.consume_log_path_notice() is None


def test_phrase_resource_defaults_to_package_data_and_supports_override(
    base_settings_data: dict[str, object], tmp_path: Path
) -> None:
    bundled = Settings(_env_file=None, **base_settings_data)
    override_path = tmp_path / "phrases.json"
    overridden = Settings(
        _env_file=None,
        **base_settings_data,
        PETEEEBOT_PHRASES_FILE=override_path,
    )

    assert bundled.phrases_path.is_file()
    assert bundled.phrases_path.name == "phrases_tagged.json"
    assert overridden.phrases_path == override_path


def test_operational_cron_and_backup_settings_are_accepted(base_settings_data: dict[str, object]) -> None:
    settings_value = Settings(
        _env_file=None,
        **base_settings_data,
        DUCKDNS_DOMAIN="example-domain",
        DUCKDNS_TOKEN="test-duck-token",
        BACKUP_CLOUD_UPLOAD=True,
        DROPBOX_BACKUP_DIR="/Pete-Eebot Backups",
        BACKUP_ENCRYPTION_KEY_FILE="/opt/myapp/shared/.backup_key",
        PETEEEBOT_ENV_FILE="/opt/myapp/shared/.env",
        WITHINGS_TOKEN_FILE="/opt/myapp/shared/runtime/withings/.withings_tokens.json",
        PETEEEBOT_CLI_BIN="/opt/myapp/shared/venv/bin/pete",
        PETEEEBOT_RESTART_TIMEOUT_SECONDS=30,
    )

    assert settings_value.DUCKDNS_DOMAIN == "example-domain"
    assert settings_value.DUCKDNS_TOKEN is not None
    assert settings_value.DUCKDNS_TOKEN.get_secret_value() == "test-duck-token"
    assert settings_value.BACKUP_CLOUD_UPLOAD is True
    assert settings_value.DROPBOX_BACKUP_DIR == "/Pete-Eebot Backups"
    assert settings_value.BACKUP_ENCRYPTION_KEY_FILE == Path("/opt/myapp/shared/.backup_key")
    assert settings_value.PETEEEBOT_ENV_FILE == Path("/opt/myapp/shared/.env")
    assert settings_value.WITHINGS_TOKEN_FILE == Path(
        "/opt/myapp/shared/runtime/withings/.withings_tokens.json"
    )
    assert Path(settings_value.PETEEEBOT_CLI_BIN) == Path("/opt/myapp/shared/venv/bin/pete")
    assert settings_value.PETEEEBOT_RESTART_TIMEOUT_SECONDS == 30
    assert settings_value.PETEEEBOT_PLANNER_FEATURE_FLAGS == ""


def test_planner_feature_flag_setting_is_accepted(base_settings_data: dict[str, object]) -> None:
    settings_value = Settings(
        _env_file=None,
        **base_settings_data,
        PETEEEBOT_PLANNER_FEATURE_FLAGS="experimental_relaxed_session_spacing=true",
    )

    assert settings_value.PETEEEBOT_PLANNER_FEATURE_FLAGS == (
        "experimental_relaxed_session_spacing=true"
    )
