"""
Centralised config for the entire application.

This module consolidates all configuration settings, loading sensitive values
from environment variables and providing typed, validated access to them
through a singleton `settings` object.
"""

import os
from urllib.parse import quote_plus
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized application settings.

    Pydantic's BaseSettings will automatically load values from a `.env` file
    or from system environment variables. This keeps secrets out of the code
    and allows for different configurations across environments.
    """
    # Model config: Load from a .env file, and treat env vars as case-insensitive
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    # --- CORE SETTINGS ---
    # The root directory of the project.
    # We determine this by finding the parent directory of this config file.
    PROJECT_ROOT: Path = Path(__file__).parent.parent.resolve()
    ENVIRONMENT: str = "development"

    # --- API CREDENTIALS (from environment) ---
    TELEGRAM_TOKEN: str
    TELEGRAM_CHAT_ID: str
    WITHINGS_CLIENT_ID: str
    WITHINGS_CLIENT_SECRET: str
    WITHINGS_REDIRECT_URI: str
    WITHINGS_REFRESH_TOKEN: str
    WGER_API_KEY: str
    WGER_API_URL: str = "https://wger.de/api/v2"

    # --- DATABASE (from environment) ---
    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_HOST: Optional[str] = None
    POSTGRES_PORT: Optional[int] = 5432
    POSTGRES_DB: Optional[str] = None
    DATABASE_URL: Optional[str] = Field(None, validate_default=True)

    # --- PROGRESSION SETTINGS ---
    PROGRESSION_INCREMENT: float = 0.05  # 5 percent increase
    PROGRESSION_DECREMENT: float = 0.05  # 5 percent decrease

    # --- RECOVERY & VALIDATION THRESHOLDS ---
    RHR_ALLOWED_INCREASE: float = 0.10  # 10% above baseline triggers back-off
    SLEEP_ALLOWED_DECREASE: float = 0.85  # 85% of baseline triggers back-off
    BODY_AGE_ALLOWED_INCREASE: float = 2.0  # years
    GLOBAL_BACKOFF_FACTOR: float = 0.90  # reduce weights by 10%

    # --- METRIC WINDOWS ---
    BASELINE_DAYS: int = 28
    CYCLE_DAYS: int = 28

    # --- PLAN BUILDER RECOVERY THRESHOLDS ---
    RECOVERY_SLEEP_THRESHOLD_MINUTES: int = 420  # 7 hours
    RECOVERY_RHR_THRESHOLD: int = 60  # bpm

    def __init__(self, **values):
        super().__init__(**values)
        # --- THIS LOGIC IS UPDATED ---
        # Check for an explicit override for the host from the environment
        db_host = os.getenv("DB_HOST_OVERRIDE", self.POSTGRES_HOST)
        if self.POSTGRES_USER and self.POSTGRES_PASSWORD and db_host and self.POSTGRES_DB:
            # URL-encode user/pass to support special characters like @ and #
            user_enc = quote_plus(self.POSTGRES_USER)
            pass_enc = quote_plus(self.POSTGRES_PASSWORD)
            self.DATABASE_URL = (
                f"postgresql://{user_enc}:{pass_enc}@{db_host}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        else:
            self.DATABASE_URL = None


    # --- FILE PATHS (derived from PROJECT_ROOT) ---
    @property
    def log_path(self) -> Path:
        return self.PROJECT_ROOT / "summaries/logs/pete_history.log"

    @property
    def lift_log_path(self) -> Path:
        return self.PROJECT_ROOT / "knowledge/lift_log.json"

    @property
    def history_path(self) -> Path:
        return self.PROJECT_ROOT / "knowledge/history.json"

    @property
    def daily_knowledge_path(self) -> Path:
        return self.PROJECT_ROOT / "knowledge/daily"

    @property
    def wger_catalog_path(self) -> Path:
        return self.PROJECT_ROOT / "knowledge/wger"

    @property
    def phrases_path(self) -> Path:
        return self.PROJECT_ROOT / "knowledge/phrases.json"

    @property
    def wger_plans_path(self) -> Path:
        return self.PROJECT_ROOT / "knowledge/wger/plans"

    @property
    def body_age_path(self) -> Path:
        return self.PROJECT_ROOT / "knowledge/body_age.json"


# Create a single, importable instance of the settings
settings = Settings()
