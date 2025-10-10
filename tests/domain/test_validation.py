# tests/test_validation.py
from datetime import date, timedelta
import sys
import types
from pathlib import Path
from typing import List, Dict, Any

import pytest

# ---- Stubs for settings and logging paths, injected before import ----

if "pete_e.config" not in sys.modules:
    config_stub = types.ModuleType("pete_e.config")

    class _SettingsStub:
        # thresholds align with the shared config stub
        RHR_ALLOWED_INCREASE = 0.10
        SLEEP_ALLOWED_DECREASE = 0.85
        HRV_ALLOWED_DECREASE = 0.12

        def __getattr__(self, name):
            return None

        @property
        def log_path(self):
            # will be overridden by fixture to tmp_path
            return Path("logs/test_validation.log")

    config_stub.settings = _SettingsStub()
    config_stub.get_env = lambda key, default=None: default
    sys.modules["pete_e.config"] = config_stub

if "pete_e.infrastructure.log_utils" not in sys.modules:
    # Provide a minimal log_utils that does nothing, to avoid file writes before tmp patch
    lu = types.ModuleType("pete_e.infrastructure.log_utils")

    def _noop(msg: str, level: str = "INFO"):
        pass

    lu.log_message = _noop
    sys.modules["pete_e.infrastructure.log_utils"] = lu

# Import after stubbing
from pete_e.domain.validation import (
    assess_recovery_and_backoff,
    compute_dynamic_baselines,
)


def _make_rows(base_date: date, days: int, rhr: float, sleep_min: int) -> List[Dict[str, Any]]:
    """Produce 'days' rows ending at base_date with constant hr_resting and sleep_total_minutes."""
    rows: List[Dict[str, Any]] = []
    for i in range(days):
        d = base_date - timedelta(days=i)
        rows.append(
            {
                "date": d,
                "hr_resting": float(rhr),
                "sleep_total_minutes": float(sleep_min),
            }
        )
    return rows


@pytest.fixture(autouse=True)
def patch_log_path(tmp_path, monkeypatch):
    from pete_e import config as cfg

    # Patch the stubbed settings object’s log_path property
    monkeypatch.setattr(
        cfg.settings.__class__,
        "log_path",
        property(lambda self: tmp_path / "test_validation.log"),
    )



def test_baselines_use_recent_medians():
    today = date.today()
    # 180 days at rhr 50, sleep 420
    hist = _make_rows(today, 180, rhr=50.0, sleep_min=420)
    bl = compute_dynamic_baselines(hist, reference_end_date=today)
    assert bl["hr_resting"].value == pytest.approx(50.0, abs=1e-6)
    assert bl["sleep_total_minutes"].value == pytest.approx(420.0, abs=1e-6)


def test_baselines_accept_prefetched_rows():
    today = date.today()
    hist = _make_rows(today, 45, rhr=52.0, sleep_min=400)

    bl = compute_dynamic_baselines(hist, reference_end_date=today)

    assert bl["hr_resting"].value == pytest.approx(52.0, abs=1e-6)
    assert bl["sleep_total_minutes"].value == pytest.approx(400.0, abs=1e-6)


def test_backoff_none_when_within_thresholds():
    today = date.today()
    rows = _make_rows(today, 180, rhr=50.0, sleep_min=420)

    # Next week starts tomorrow, so last 7 complete days are within the synthetic series
    rec = assess_recovery_and_backoff(rows, week_start_date=today + timedelta(days=1))
    assert rec.needs_backoff is False
    assert rec.severity == "none"


def test_backoff_triggers_on_rhr_increase():
    today = date.today()
    # Long-term baseline 50, but the last 7 days should average ~55 (+10%)
    rows = _make_rows(today - timedelta(days=7), 173, rhr=50.0, sleep_min=420)
    rows += _make_rows(today, 7, rhr=55.0, sleep_min=420)

    rec = assess_recovery_and_backoff(rows, week_start_date=today + timedelta(days=1))
    assert rec.needs_backoff is True
    assert rec.severity in {"mild", "moderate", "severe"}
    # Given thresholds (5%), 10% excess -> ratio 2.0 -> moderate or above
    assert rec.metrics["rhr_baseline"] == pytest.approx(50.0, abs=1e-6)


def test_backoff_triggers_on_sleep_drop():
    today = date.today()
    # Long-term baseline sleep 420, last 7 days drop to 360 (-14.3%)
    rows = _make_rows(today - timedelta(days=7), 173, rhr=50.0, sleep_min=420)
    rows += _make_rows(today, 7, rhr=50.0, sleep_min=360)

    rec = assess_recovery_and_backoff(rows, week_start_date=today + timedelta(days=1))
    assert rec.needs_backoff is True
    assert rec.severity in {"mild", "moderate", "severe"}
    assert rec.metrics["sleep_baseline"] == pytest.approx(420.0, abs=1e-6)
