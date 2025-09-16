"""
Centralised config for the entire application.

This module consolidates all configuration settings, loading sensitive values
from environment variables and providing typed, validated access to them
through a singleton `settings` object.
"""

import os
from pathlib import Path
from typing import Optional

from datetime import date
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from psycopg.conninfo import make_conninfo


class Settings(BaseSettings):
    """
    Centralized application settings.
    """
    # Model config: Load from a .env file, and treat env vars as case-insensitive
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    # --- CORE SETTINGS ---
    PROJECT_ROOT: Path = Path(__file__).parent.parent.resolve()
    ENVIRONMENT: str = "development"

    # --- USER METRICS (from environment) ---
    USER_DATE_OF_BIRTH: date
    USER_HEIGHT_CM: int
    USER_GOAL_WEIGHT_KG: float

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

    # --- PROGRESSION & RECOVERY THRESHOLDS ---
    PROGRESSION_INCREMENT: float = 0.05
    PROGRESSION_DECREMENT: float = 0.05
    RHR_ALLOWED_INCREASE: float = 0.10
    SLEEP_ALLOWED_DECREASE: float = 0.85
    BODY_AGE_ALLOWED_INCREASE: float = 2.0
    GLOBAL_BACKOFF_FACTOR: float = 0.90

    # --- METRIC WINDOWS ---
    BASELINE_DAYS: int = 28
    CYCLE_DAYS: int = 28

    # --- PLAN BUILDER RECOVERY THRESHOLDS ---
    RECOVERY_SLEEP_THRESHOLD_MINUTES: int = 420
    RECOVERY_RHR_THRESHOLD: int = 60

    def __init__(self, **values):
        super().__init__(**values)
        db_host = os.getenv("DB_HOST_OVERRIDE", self.POSTGRES_HOST)
        if self.POSTGRES_USER and self.POSTGRES_PASSWORD and db_host and self.POSTGRES_DB:
            self.DATABASE_URL = make_conninfo(
                user=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=db_host,
                port=self.POSTGRES_PORT,
                dbname=self.POSTGRES_DB,
            )
        else:
            self.DATABASE_URL = None

    # --- ACTIVE FILE PATHS ---
    @property
    def log_path(self) -> Path:
        """
        Path for the main application log file.
        Uses /var/log/pete_eebot if available (standard for Linux),
        otherwise falls back to a local ./logs directory.
        """
        # The standard path for a production-like environment
        prod_log_dir = Path("/var/log/pete_eebot")
        
        # Check if the directory exists and is writable
        if prod_log_dir.exists() and os.access(prod_log_dir, os.W_OK):
            return prod_log_dir / "pete_history.log"
        else:
            # Fallback for local development
            local_log_dir = self.PROJECT_ROOT / "logs"
            local_log_dir.mkdir(exist_ok=True)
            return local_log_dir / "pete_history.log"

    @property
    def phrases_path(self) -> Path:
        """Path to the tagged phrases resource file."""
        return self.PROJECT_ROOT / "pete_e/resources/phrases_tagged.json"

    @property
    def apple_incoming_path(self) -> Path:
        """Directory where Tailscale places incoming Apple Health zips."""
        return self.PROJECT_ROOT / "apple-incoming"

    @property
    def apple_processed_path(self) -> Path:
        """Directory to archive processed Apple Health zips."""
        return self.PROJECT_ROOT / "apple-processed"


# Create a single, importable instance of the settings
settings = Settings()