import os


def pytest_configure():
    """Set minimal environment variables so Settings can initialise during tests."""

    defaults = {
        "USER_DATE_OF_BIRTH": "1990-01-01",
        "USER_HEIGHT_CM": "180",
        "USER_GOAL_WEIGHT_KG": "80",
        "TELEGRAM_TOKEN": "dummy",
        "TELEGRAM_CHAT_ID": "123",
        "WITHINGS_CLIENT_ID": "dummy",
        "WITHINGS_CLIENT_SECRET": "dummy",
        "WITHINGS_REDIRECT_URI": "https://example.com",
        "WITHINGS_REFRESH_TOKEN": "dummy",
        "WGER_API_KEY": "dummy",
        "DROPBOX_HEALTH_METRICS_DIR": "/health",
        "DROPBOX_WORKOUTS_DIR": "/workouts",
        "DROPBOX_APP_KEY": "dummy",
        "DROPBOX_APP_SECRET": "dummy",
        "DROPBOX_REFRESH_TOKEN": "dummy",
        "GH_SECRETS_TOKEN": "dummy",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_DB": "postgres",
    }

    for key, value in defaults.items():
        os.environ.setdefault(key, value)

