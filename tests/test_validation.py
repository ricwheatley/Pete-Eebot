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
        # thresholds: 5% RHR allowed increase, 10% sleep allowed decrease
        RHR_ALLOWED_INCREASE = 0.05
        SLEEP_ALLOWED_DECREASE = 0.10

        def __getattr__(self, name):
            return None

        @property
        def log_path(self):
            # will be overridden by fixture to tmp_path
            return Path("logs/test_validation.log")

    config_stub.settings = _SettingsStub()
    sys.modules["pete_e.config"] = config_stub

if "pete_e.infra.log_utils" not in sys.modules:
    # Provide a minimal log_utils that does nothing, to avoid file writes before tmp patch
    lu = types.ModuleType("pete_e.infra.log_utils")

    def _noop(msg: str, level: str = "INFO"):
        pass

    lu.log_message = _noop
    sys.modules["pete_e.infra.log_utils"] = lu

# Import after stubbing
from pete_e.core.validation import (
    assess_recovery_and_backoff,
    compute_dynamic_baselines,
)


class _DalStub:
    """Stub DAL that synthesises historical rows on demand."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        # return rows filtered to the inclusive window
        out: List[Dict[str, Any]] = []
        for r in self._rows:
            d = r.get("date")
            if d and start_date <= d <= end_date:
                out.append(r)
        return out


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
    # ensure any real logger uses a tmp file path
    from pete_e import config as cfg
    class _Settings(cfg.settings.__class__):  # type: ignore
        @property
        def log_path(self):  # pragma: no cover
            return tmp_path / "test_validation.log"
    monkeypatch.setattr(cfg, "settings", _Settings())


def test_baselines_use_recent_medians():
    today = date.today()
    # 180 days at rhr 50, sleep 420
    hist = _make_rows(today, 180, rhr=50.0, sleep_min=420)
    dal = _DalStub(hist)

    bl = compute_dynamic_baselines(dal, reference_end_date=today)
    assert bl["hr_resting"].value == pytest.approx(50.0, abs=1e-6)
    assert bl["sleep_total_minutes"].value == pytest.approx(420.0, abs=1e-6)


def test_backoff_none_when_within_thresholds():
    today = date.today()
    rows = _make_rows(today, 180, rhr=50.0, sleep_min=420)
    dal = _DalStub(rows)

    # Next week starts tomorrow, so last 7 complete days are within the synthetic series
    rec = assess_recovery_and_backoff(dal, week_start_date=today + timedelta(days=1))
    assert rec.needs_backoff is False
    assert rec.severity == "none"


def test_backoff_triggers_on_rhr_increase():
    today = date.today()
    # Long-term baseline 50, but the last 7 days should average ~55 (+10%)
    rows = _make_rows(today - timedelta(days=7), 173, rhr=50.0, sleep_min=420)
    rows += _make_rows(today, 7, rhr=55.0, sleep_min=420)

    dal = _DalStub(rows)
    rec = assess_recovery_and_backoff(dal, week_start_date=today + timedelta(days=1))
    assert rec.needs_backoff is True
    assert rec.severity in {"mild", "moderate", "severe"}
    # Given thresholds (5%), 10% excess -> ratio 2.0 -> moderate or above
    assert rec.metrics["rhr_baseline"] == pytest.approx(50.0, abs=1e-6)


def test_backoff_triggers_on_sleep_drop():
    today = date.today()
    # Long-term baseline sleep 420, last 7 days drop to 360 (-14.3%)
    rows = _make_rows(today - timedelta(days=7), 173, rhr=50.0, sleep_min=420)
    rows += _make_rows(today, 7, rhr=50.0, sleep_min=360)

    dal = _DalStub(rows)
    rec = assess_recovery_and_backoff(dal, week_start_date=today + timedelta(days=1))
    assert rec.needs_backoff is True
    assert rec.severity in {"mild", "moderate", "severe"}
    assert rec.metrics["sleep_baseline"] == pytest.approx(420.0, abs=1e-6)
