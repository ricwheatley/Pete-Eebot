"""Additional unit coverage for progression helper functions."""
from __future__ import annotations

import pytest

from pete_e.domain.progression import _adjust_exercise, _compute_recovery_flag
from pete_e.config import settings
from tests import config_stub  # noqa: F401 - ensure stub settings loaded


def _make_metrics(rhr: float | None, sleep: float | None, count: int):
    return [
        {"hr_resting": rhr, "sleep_asleep_minutes": sleep}
        for _ in range(count)
    ]


def test_compute_recovery_flag_defaults_to_true_with_missing_data():
    assert _compute_recovery_flag([], []) is True
    metrics = _make_metrics(None, 400, 7)
    baseline = _make_metrics(50, 400, settings.BASELINE_DAYS)
    assert _compute_recovery_flag(metrics, baseline) is True


def test_compute_recovery_flag_detects_poor_recovery():
    metrics = _make_metrics(60, 300, 7)
    baseline = _make_metrics(50, 420, settings.BASELINE_DAYS)
    assert _compute_recovery_flag(metrics, baseline) is False


def test_adjust_exercise_with_no_history_returns_message():
    exercise = {"id": 1, "name": "Back Squat", "weight_target": 100.0}
    new_weight, message = _adjust_exercise(exercise, [], recovery_good=True)
    assert new_weight is None
    assert "no history" in message


def test_adjust_exercise_increases_weight_when_rir_low():
    exercise = {"id": 1, "name": "Bench", "weight_target": 100.0}
    history = [
        {"weight": 100.0, "rir": 0.5},
        {"weight": 100.0, "rir": 1.0},
        {"weight": 100.0, "rir": 1.0},
        {"weight": 100.0, "rir": 0.5},
    ]
    new_weight, message = _adjust_exercise(exercise, history, recovery_good=True)
    assert new_weight == pytest.approx(100.0 * (1 + settings.PROGRESSION_INCREMENT * 1.5))
    assert "+" in message and "recovery good" in message


def test_adjust_exercise_decreases_weight_for_high_rir():
    exercise = {"id": 2, "name": "Rows", "weight_target": 80.0}
    history = [
        {"weight": 80.0, "rir": 3.0},
        {"weight": 80.0, "rir": 3.0},
        {"weight": 80.0, "rir": 2.5},
        {"weight": 80.0, "rir": 2.5},
    ]
    new_weight, message = _adjust_exercise(exercise, history, recovery_good=True)
    expected = round(80.0 * (1 - settings.PROGRESSION_DECREMENT), 2)
    assert new_weight == pytest.approx(expected)
    assert "-" in message and "recovery good" in message


def test_adjust_exercise_handles_missing_weight_entries():
    exercise = {"id": 3, "name": "Deadlift", "weight_target": 120.0}
    history = [{"weight": None, "rir": 1.0} for _ in range(4)]
    new_weight, message = _adjust_exercise(exercise, history, recovery_good=False)
    assert new_weight is None
    assert "no valid weight data" in message
    assert "recovery poor" in message
