"""
Centralised config for the entire application.

This module consolidates all configuration settings, loading sensitive values
from environment variables and providing typed, validated access to them
through a singleton `settings` object.
"""

import os
from datetime import date
from pathlib import Path
from typing import Optional

from psycopg.conninfo import make_conninfo
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
ENV_FILE_PATH = PROJECT_ROOT / ".env"

class Settings(BaseSettings):
    """
    Centralised and validated application settings.
    """
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # --- CORE APP SETTINGS ---
    PROJECT_ROOT: Path = Path(__file__).parent.parent.resolve()
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
    
    # --- DROPBOX (from environment) ---
    DROPBOX_HEALTH_METRICS_DIR: str
    DROPBOX_WORKOUTS_DIR: str
    DROPBOX_APP_KEY: str
    DROPBOX_APP_SECRET: str
    DROPBOX_REFRESH_TOKEN: str

    # --- API KEYS (from environment) ---
    PETEEEBOT_API_KEY: str
    
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

    def __init__(self, **values):
        """Dynamically constructs the DATABASE_URL after initial validation."""
        super().__init__(**values)
        db_host = os.getenv("DB_HOST_OVERRIDE", self.POSTGRES_HOST)
        
        self.DATABASE_URL = make_conninfo(
            user=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=db_host,
            port=self.POSTGRES_PORT,
            dbname=self.POSTGRES_DB,
        )

    # --- DYNAMIC FILE PATHS ---
    @property
    def log_path(self) -> Path:
        """
        Path for the main application log file.
        """
        prod_log_dir = Path("/var/log/pete_eebot")
        if prod_log_dir.exists() and os.access(prod_log_dir, os.W_OK):
            return prod_log_dir / "pete_history.log"
        else:
            local_log_dir = self.PROJECT_ROOT / "logs"
            local_log_dir.mkdir(exist_ok=True)
            return local_log_dir / "pete_history.log"

    @property
    def phrases_path(self) -> Path:
        """Path to the tagged phrases resource file."""
        return self.PROJECT_ROOT / "pete_e/resources/phrases_tagged.json"


# Create a single, importable instance of the settings for the entire application.
settings = Settings()

