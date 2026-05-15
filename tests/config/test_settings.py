from datetime import date
import pytest
from psycopg.conninfo import make_conninfo

from pete_e.config.config import Settings


@pytest.fixture()
def base_settings_data() -> dict:
    return {
        "USER_DATE_OF_BIRTH": date(1990, 1, 1),
        "USER_HEIGHT_CM": 180,
        "USER_GOAL_WEIGHT_KG": 80.0,
        "TELEGRAM_TOKEN": "telegram-token",
        "TELEGRAM_CHAT_ID": "chat-id",
        "WITHINGS_CLIENT_ID": "withings-client-id",
        "WITHINGS_CLIENT_SECRET": "withings-client-secret",
        "WITHINGS_REDIRECT_URI": "https://example.com/redirect",
        "WITHINGS_REFRESH_TOKEN": "withings-refresh-token",
        "WGER_API_KEY": "wger-api-key",
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
    }
    """Perform base settings data."""


def test_database_url_uses_postgres_host(monkeypatch: pytest.MonkeyPatch, base_settings_data: dict) -> None:
    monkeypatch.delenv("DB_HOST_OVERRIDE", raising=False)
    settings = Settings(**base_settings_data)

    expected = make_conninfo(
        user=base_settings_data["POSTGRES_USER"],
        password=base_settings_data["POSTGRES_PASSWORD"],
        host=base_settings_data["POSTGRES_HOST"],
        port=base_settings_data["POSTGRES_PORT"],
        dbname=base_settings_data["POSTGRES_DB"],
    )

    assert settings.DATABASE_URL == expected
    """Perform test database url uses postgres host."""


def test_database_url_uses_override(monkeypatch: pytest.MonkeyPatch, base_settings_data: dict) -> None:
    override_host = "override-host"
    monkeypatch.setenv("DB_HOST_OVERRIDE", override_host)
    settings = Settings(**base_settings_data)

    expected = make_conninfo(
        user=base_settings_data["POSTGRES_USER"],
        password=base_settings_data["POSTGRES_PASSWORD"],
        host=override_host,
        port=base_settings_data["POSTGRES_PORT"],
        dbname=base_settings_data["POSTGRES_DB"],
    )

    assert settings.DATABASE_URL == expected
    assert settings.WGER_EXPAND_STRETCH_ROUTINES is False
    """Perform test database url uses override."""


def test_log_path_fallback_notice_is_consumed_once(
    monkeypatch: pytest.MonkeyPatch,
    base_settings_data: dict,
    tmp_path,
) -> None:
    settings = Settings(**base_settings_data)
    fallback_path = tmp_path / "pete_history.log"

    monkeypatch.setattr(
        Settings,
        "_resolve_log_path",
        lambda self: (fallback_path, "fallback notice"),
    )

    assert settings.log_path == fallback_path
    assert settings.consume_log_path_notice() == "fallback notice"
    assert settings.consume_log_path_notice() is None
    """Perform test log path fallback notice is consumed once."""


def test_operational_cron_and_backup_settings_are_accepted(base_settings_data: dict) -> None:
    settings = Settings(
        **base_settings_data,
        DUCKDNS_DOMAIN="example-domain",
        DUCKDNS_TOKEN="duckdns-token",
        BACKUP_CLOUD_UPLOAD=True,
        DROPBOX_BACKUP_DIR="/Pete-Eebot Backups",
        BACKUP_ENCRYPTION_KEY_FILE="/home/pi/.backup_key",
        PETEEEBOT_RESTART_TIMEOUT_SECONDS=30,
    )

    assert settings.DUCKDNS_DOMAIN == "example-domain"
    assert settings.DUCKDNS_TOKEN is not None
    secret_getter = getattr(settings.DUCKDNS_TOKEN, "get_secret_value", None)
    secret_value = secret_getter() if callable(secret_getter) else settings.DUCKDNS_TOKEN
    assert secret_value == "duckdns-token"
    assert settings.BACKUP_CLOUD_UPLOAD is True
    assert settings.DROPBOX_BACKUP_DIR == "/Pete-Eebot Backups"
    assert settings.BACKUP_ENCRYPTION_KEY_FILE is not None
    assert str(settings.BACKUP_ENCRYPTION_KEY_FILE) == "/home/pi/.backup_key"
    assert settings.PETEEEBOT_RESTART_TIMEOUT_SECONDS == 30
    assert settings.PETEEEBOT_PLANNER_FEATURE_FLAGS == ""
    """Perform test operational cron and backup settings are accepted."""


def test_planner_feature_flag_setting_is_accepted(base_settings_data: dict) -> None:
    settings = Settings(
        **base_settings_data,
        PETEEEBOT_PLANNER_FEATURE_FLAGS="experimental_relaxed_session_spacing=true",
    )

    assert settings.PETEEEBOT_PLANNER_FEATURE_FLAGS == "experimental_relaxed_session_spacing=true"
