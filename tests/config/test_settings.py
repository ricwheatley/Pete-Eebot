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
