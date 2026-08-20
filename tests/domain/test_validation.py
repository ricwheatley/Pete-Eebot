# tests/test_validation.py
from datetime import date, timedelta
from typing import List, Dict, Any

import pytest
from pete_e.domain.validation import (
    assess_recovery_and_backoff,
    calculate_effective_prescription,
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
    """Perform patch log path."""



def test_baselines_use_recent_medians():
    today = date.today()
    # 180 days at rhr 50, sleep 420
    hist = _make_rows(today, 180, rhr=50.0, sleep_min=420)
    bl = compute_dynamic_baselines(hist, reference_end_date=today)
    assert bl["hr_resting"].value == pytest.approx(50.0, abs=1e-6)
    assert bl["sleep_total_minutes"].value == pytest.approx(420.0, abs=1e-6)
    """Perform test baselines use recent medians."""


def test_baselines_accept_prefetched_rows():
    today = date.today()
    hist = _make_rows(today, 45, rhr=52.0, sleep_min=400)

    bl = compute_dynamic_baselines(hist, reference_end_date=today)

    assert bl["hr_resting"].value == pytest.approx(52.0, abs=1e-6)
    assert bl["sleep_total_minutes"].value == pytest.approx(400.0, abs=1e-6)
    """Perform test baselines accept prefetched rows."""


def test_backoff_none_when_within_thresholds():
    today = date.today()
    rows = _make_rows(today, 180, rhr=50.0, sleep_min=420)

    # Next week starts tomorrow, so last 7 complete days are within the synthetic series
    rec = assess_recovery_and_backoff(rows, week_start_date=today + timedelta(days=1))
    assert rec.needs_backoff is False
    assert rec.severity == "none"
    """Perform test backoff none when within thresholds."""


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
    """Perform test backoff triggers on rhr increase."""


def test_backoff_triggers_on_sleep_drop():
    today = date.today()
    # Long-term baseline sleep 420, last 7 days drop to 360 (-14.3%)
    rows = _make_rows(today - timedelta(days=7), 173, rhr=50.0, sleep_min=420)
    rows += _make_rows(today, 7, rhr=50.0, sleep_min=360)

    rec = assess_recovery_and_backoff(rows, week_start_date=today + timedelta(days=1))
    assert rec.needs_backoff is True
    assert rec.severity in {"mild", "moderate", "severe"}
    assert rec.metrics["sleep_baseline"] == pytest.approx(420.0, abs=1e-6)
    """Perform test backoff triggers on sleep drop."""


def test_effective_prescription_is_always_calculated_from_baseline() -> None:
    first = calculate_effective_prescription(
        baseline_sets=5,
        baseline_rir=2.0,
        set_multiplier=0.8,
        rir_increment=1,
    )
    repeated = calculate_effective_prescription(
        baseline_sets=5,
        baseline_rir=2.0,
        set_multiplier=0.8,
        rir_increment=1,
    )

    assert first == repeated
    assert (first.sets, first.rir) == (4, 3.0)


def test_neutral_effective_prescription_preserves_null_baseline_rir() -> None:
    result = calculate_effective_prescription(
        baseline_sets=3,
        baseline_rir=None,
        set_multiplier=1.0,
        rir_increment=0,
    )

    assert result.sets == 3
    assert result.rir is None


def test_zero_set_placeholder_is_not_adjusted() -> None:
    result = calculate_effective_prescription(
        baseline_sets=0,
        baseline_rir=None,
        set_multiplier=0.8,
        rir_increment=1,
    )

    assert result.sets == 0
    assert result.rir is None
