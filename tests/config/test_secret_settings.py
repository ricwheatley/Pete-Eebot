from __future__ import annotations

import logging

from pydantic import SecretStr, ValidationError
import pytest

from pete_e.config.config import Settings


pytestmark = pytest.mark.contract


def _sentinel(*parts: str) -> str:
    return "-".join(("s02", "generated", *parts))


_PLAIN_CREDENTIAL_FIELDS = {
    "WGER_PASSWORD": _sentinel("wger", "password"),
    "DROPBOX_APP_KEY": _sentinel("dropbox", "app", "key"),
    "DROPBOX_APP_SECRET": _sentinel("dropbox", "app", "secret"),
    "DROPBOX_REFRESH_TOKEN": _sentinel("dropbox", "refresh"),
    "PETEEEBOT_API_KEY": _sentinel("machine", "api", "key"),
}


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name, raising=False)
    monkeypatch.delenv("DB_HOST_OVERRIDE", raising=False)


def _settings_values() -> dict[str, object]:
    return {
        "USER_DATE_OF_BIRTH": "1990-01-01",
        "USER_HEIGHT_CM": 180,
        "USER_GOAL_WEIGHT_KG": 80.0,
        "TELEGRAM_TOKEN": _sentinel("telegram", "token"),
        "TELEGRAM_CHAT_ID": _sentinel("chat", "id"),
        "WITHINGS_CLIENT_ID": _sentinel("withings", "client", "id"),
        "WITHINGS_CLIENT_SECRET": _sentinel("withings", "client", "secret"),
        "WITHINGS_REDIRECT_URI": "https://example.invalid/callback",
        "WITHINGS_REFRESH_TOKEN": _sentinel("withings", "refresh"),
        "WGER_API_KEY": _sentinel("wger", "api", "key"),
        "WGER_USERNAME": _sentinel("wger", "user"),
        "DROPBOX_HEALTH_METRICS_DIR": "health",
        "DROPBOX_WORKOUTS_DIR": "workouts",
        "DATABASE_URL": (
            "postgresql://s02-user:"
            + _sentinel("db", "password")
            + "@db.invalid:5432/database"
        ),
        **_PLAIN_CREDENTIAL_FIELDS,
    }


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**_settings_values(), **overrides})


def _assert_error_is_secret_safe(
    error: ValidationError,
    sentinels: list[str],
) -> None:
    renderings = (
        str(error),
        repr(error),
        error.json(),
        repr(error.errors()),
    )
    for sentinel in sentinels:
        assert all(sentinel not in rendering for rendering in renderings)
    assert all(detail.get("input") is None for detail in error.errors())


def test_complete_credential_inventory_uses_secret_types() -> None:
    settings_value = _settings()

    for field_name in _PLAIN_CREDENTIAL_FIELDS:
        assert isinstance(getattr(settings_value, field_name), SecretStr)

    for field_name in (
        "DATABASE_URL",
        "TELEGRAM_TOKEN",
        "WITHINGS_CLIENT_SECRET",
        "WITHINGS_REFRESH_TOKEN",
        "WGER_API_KEY",
    ):
        assert isinstance(getattr(settings_value, field_name), SecretStr)

    for identifier_field in (
        "TELEGRAM_CHAT_ID",
        "WITHINGS_CLIENT_ID",
        "WITHINGS_REDIRECT_URI",
        "WGER_USERNAME",
    ):
        assert isinstance(getattr(settings_value, identifier_field), str)
        assert not isinstance(getattr(settings_value, identifier_field), SecretStr)


def test_settings_representations_serialization_and_debug_logs_are_secret_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings_value = _settings()
    caplog.set_level(logging.DEBUG, logger="tests.s02.settings")

    logging.getLogger("tests.s02.settings").debug(
        "settings str=%s repr=%r",
        settings_value,
        settings_value,
    )

    renderings = (
        str(settings_value),
        repr(settings_value),
        repr(settings_value.model_dump()),
        repr(settings_value.model_dump(mode="json")),
        settings_value.model_dump_json(),
        caplog.text,
    )
    for sentinel in _PLAIN_CREDENTIAL_FIELDS.values():
        assert all(sentinel not in rendering for rendering in renderings)


def test_field_validation_error_omits_invalid_credential_input() -> None:
    invalid_secret = 918_273_645

    with pytest.raises(ValidationError) as exc_info:
        _settings(DROPBOX_APP_SECRET=invalid_secret)

    assert exc_info.value.errors()[0]["loc"] == ("DROPBOX_APP_SECRET",)
    _assert_error_is_secret_safe(exc_info.value, [str(invalid_secret)])


def test_model_validation_error_omits_complete_credential_input() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(
            PETEEEBOT_JOB_LEASE_SECONDS=300,
            PETEEEBOT_JOB_HEARTBEAT_SECONDS=150,
        )

    assert "must be less than half" in str(exc_info.value)
    _assert_error_is_secret_safe(
        exc_info.value,
        list(_PLAIN_CREDENTIAL_FIELDS.values()),
    )


def test_dotenv_names_and_plaintext_provider_values_remain_compatible(tmp_path) -> None:
    env_file = tmp_path / "s02-settings.env"
    values = _settings_values()
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )

    settings_value = Settings(_env_file=env_file)

    for field_name, sentinel in _PLAIN_CREDENTIAL_FIELDS.items():
        secret = getattr(settings_value, field_name)
        assert isinstance(secret, SecretStr)
        assert secret.get_secret_value() == sentinel


def test_optional_secret_credentials_preserve_none() -> None:
    settings_value = _settings(WGER_PASSWORD=None, PETEEEBOT_API_KEY=None)

    assert settings_value.WGER_PASSWORD is None
    assert settings_value.PETEEEBOT_API_KEY is None
