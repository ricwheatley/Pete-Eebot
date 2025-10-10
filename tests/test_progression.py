from __future__ import annotations

from typing import Any, Dict, List

from pete_e.config import settings
from pete_e.domain.progression import apply_progression

from tests import config_stub  # noqa: F401 - ensure pete_e.config is stubbed


def make_metrics(rhr: float, sleep: float, days: int) -> List[Dict[str, Any]]:
    return [
        {"hr_resting": rhr, "sleep_asleep_minutes": sleep}
        for _ in range(days)
    ]


def make_week(target: float = 100.0, ex_id: int = 1) -> dict:
    return {
        "days": [
            {
                "sessions": [
                    {
                        "type": "weights",
                        "exercises": [
                            {"id": ex_id, "name": "Test", "weight_target": target}
                        ],
                    }
                ]
            }
        ]
    }


def _run_progression(
    *,
    lift_history: Dict[str, List[Dict[str, Any]]],
    metrics: List[Dict[str, Any]],
    baseline: List[Dict[str, Any]],
    week: dict | None = None,
) -> tuple[dict, List[str]]:
    week_structure = week or make_week()
    return apply_progression(
        week_structure,
        lift_history=lift_history,
        recent_metrics=metrics,
        baseline_metrics=baseline,
    )


def test_low_rir_good_recovery() -> None:
    lift_history = {
        "1": [
            {"weight": 100, "rir": 0.5},
            {"weight": 100, "rir": 1.0},
            {"weight": 100, "rir": 1.0},
            {"weight": 100, "rir": 0.5},
        ]
    }
    metrics = make_metrics(50, 400, 7)
    baseline = make_metrics(50, 400, settings.BASELINE_DAYS)

    adjusted, notes = _run_progression(
        lift_history=lift_history, metrics=metrics, baseline=baseline
    )

    weight = adjusted["days"][0]["sessions"][0]["exercises"][0]["weight_target"]
    assert weight == 107.5
    assert any("+7.5%" in n for n in notes)
    assert any("recovery good" in n for n in notes)


def test_high_rir_good_recovery() -> None:
    lift_history = {
        "1": [
            {"weight": 100, "rir": 3.0},
            {"weight": 100, "rir": 3.0},
            {"weight": 100, "rir": 3.0},
            {"weight": 100, "rir": 3.0},
        ]
    }
    metrics = make_metrics(50, 400, 7)
    baseline = make_metrics(50, 400, settings.BASELINE_DAYS)

    adjusted, notes = _run_progression(
        lift_history=lift_history, metrics=metrics, baseline=baseline
    )

    weight = adjusted["days"][0]["sessions"][0]["exercises"][0]["weight_target"]
    assert weight == 95.0
    assert any("-5.0%" in n for n in notes)


def test_poor_recovery_halves_increment() -> None:
    lift_history = {
        "1": [
            {"weight": 100, "rir": 0.5},
            {"weight": 100, "rir": 1.0},
            {"weight": 100, "rir": 1.0},
            {"weight": 100, "rir": 0.5},
        ]
    }
    metrics = make_metrics(60, 400, 7)
    baseline = make_metrics(50, 400, settings.BASELINE_DAYS)

    adjusted, notes = _run_progression(
        lift_history=lift_history, metrics=metrics, baseline=baseline
    )

    weight = adjusted["days"][0]["sessions"][0]["exercises"][0]["weight_target"]
    assert weight == 103.75
    assert any("recovery poor" in n for n in notes)


def test_missing_history_keeps_target() -> None:
    lift_history = {
        "1": [
            {"weight": 100, "rir": 1.0},
            {"weight": 100, "rir": 1.0},
            {"weight": 100, "rir": 1.0},
            {"weight": 100, "rir": 1.0},
        ]
    }
    metrics = make_metrics(50, 400, 7)
    baseline = make_metrics(50, 400, settings.BASELINE_DAYS)

    adjusted, notes = _run_progression(
        lift_history=lift_history,
        metrics=metrics,
        baseline=baseline,
        week=make_week(target=50, ex_id=2),
    )

    weight = adjusted["days"][0]["sessions"][0]["exercises"][0]["weight_target"]
    assert weight == 50
    assert any("no history" in n for n in notes)


def test_no_rir_uses_weight_and_recovery() -> None:
    lift_history = {
        "1": [
            {"weight": 100},
            {"weight": 100},
            {"weight": 100},
            {"weight": 100},
        ]
    }
    metrics = make_metrics(50, 400, 7)
    baseline = make_metrics(50, 400, settings.BASELINE_DAYS)

    adjusted, notes = _run_progression(
        lift_history=lift_history, metrics=metrics, baseline=baseline
    )

    weight = adjusted["days"][0]["sessions"][0]["exercises"][0]["weight_target"]
    assert weight == 105.0
    assert any("no RIR" in n for n in notes)
