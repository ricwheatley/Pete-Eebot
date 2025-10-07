"""Provide a minimal pete_e.config stub for tests."""
from __future__ import annotations

import sys
import types
from datetime import date
from pathlib import Path


if "pete_e.config" not in sys.modules:
    config_module = types.ModuleType("pete_e.config")

    class _SettingsStub:
        USER_DATE_OF_BIRTH = date(1990, 1, 1)
        DATABASE_URL = "postgresql://stub"
        BASELINE_DAYS = 28
        PROGRESSION_INCREMENT = 0.05
        PROGRESSION_DECREMENT = 0.05
        RHR_ALLOWED_INCREASE = 0.10
        SLEEP_ALLOWED_DECREASE = 0.85
        HRV_ALLOWED_DECREASE = 0.12
        BODY_AGE_ALLOWED_INCREASE = 2.0
        GLOBAL_BACKOFF_FACTOR = 0.90
        CYCLE_DAYS = 28

        def __getattr__(self, name):  # pragma: no cover - defensive default
            return None

        @property
        def log_path(self):  # pragma: no cover - ensure log path is writable
            return Path("logs/test.log")

    config_module.settings = _SettingsStub()
    config_module.get_env = lambda key, default=None: default
    sys.modules["pete_e.config"] = config_module

    config_submodule = types.ModuleType("pete_e.config.config")
    config_submodule.settings = config_module.settings
    config_submodule.get_env = config_module.get_env
    sys.modules["pete_e.config.config"] = config_submodule
