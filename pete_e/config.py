import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized application settings.
    Pydantic's BaseSettings will automatically load values from environment
    variables. For example, TELEGRAM_TOKEN will be loaded from the
    TELEGRAM_TOKEN environment variable.
    """
    # Model config
    model_config = SettingsConfigDict(extra='ignore')

    # API Credentials
    WITHINGS_CLIENT_ID: str
    WITHINGS_CLIENT_SECRET: str
    WITHINGS_REDIRECT_URI: str
    WITHINGS_REFRESH_TOKEN: str
    TELEGRAM_TOKEN: str
    TELEGRAM_CHAT_ID: str
    WGER_API_KEY: str
    WGER_API_URL: str = "https://wger.de/api/v2"

    # File Paths (relative to project root)
    LOG_PATH: Path = Path("summaries/logs/pete_history.log")
    LIFT_LOG_PATH: Path = Path("knowledge/lift_log.json")
    HISTORY_PATH: Path = Path("knowledge/history.json")
    DAILY_KNOWLEDGE_PATH: Path = Path("knowledge/daily")
    WGER_CATALOG_PATH: Path = Path("knowledge/wger")
    PHRASES_PATH: Path = Path("knowledge/phrases.json")
    WGER_PLANS_PATH: Path = Path("knowledge/wger/plans")  # New path
    BODY_AGE_PATH: Path = Path("knowledge/body_age.json") # New path

    # Future Database URL placeholder
    DATABASE_URL: Optional[str] = None

# Create a single, importable instance of the settings
settings = Settings()

