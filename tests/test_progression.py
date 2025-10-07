import datetime
from typing import Any, Dict, List

from pete_e.domain.progression import apply_progression
from pete_e.config import settings
from tests import config_stub  # noqa: F401 - ensure pete_e.config is stubbed
from tests.mock_dal import MockableDal

class DummyDal(MockableDal):
    def __init__(
        self,
        lift_history: Dict[str, Any],
        metrics_7: List[Dict[str, Any]],
        metrics_baseline: List[Dict[str, Any]],
    ) -> None:
        self._lift_history = lift_history
        self._metrics_7 = metrics_7
        self._metrics_baseline = metrics_baseline

    # Lift log operations
    def load_lift_log(
        self,
        exercise_ids: List[int] | None = None,
        start_date: datetime.date | None = None,
        end_date: datetime.date | None = None,
    ) -> Dict[str, Any]:
        if exercise_ids:
            keys = {str(e) for e in exercise_ids}
            return {k: v for k, v in self._lift_history.items() if k in keys}
        return self._lift_history

    # History operations
    def load_history(self) -> Dict[str, Any]:
        return {}

    # Analytical helpers
    def load_body_age(self) -> Dict[str, Any]:
        return {}

    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        if days == 7:
            return self._metrics_7
        if days == settings.BASELINE_DAYS:
            return self._metrics_baseline
        return []


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

def test_low_rir_good_recovery():
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
    dal = DummyDal(lift_history, metrics, baseline)
    week = make_week()

    adjusted, notes = apply_progression(dal, week, None)
    weight = adjusted["days"][0]["sessions"][0]["exercises"][0]["weight_target"]
    assert weight == 107.5
    assert any("+7.5%" in n for n in notes)
    assert any("recovery good" in n for n in notes)

def test_high_rir_good_recovery():
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
    dal = DummyDal(lift_history, metrics, baseline)
    week = make_week()

    adjusted, notes = apply_progression(dal, week, None)
    weight = adjusted["days"][0]["sessions"][0]["exercises"][0]["weight_target"]
    assert weight == 95.0
    assert any("-5.0%" in n for n in notes)

def test_poor_recovery_halves_increment():
    lift_history = {
        "1": [
            {"weight": 100, "rir": 0.5},
            {"weight": 100, "rir": 1.0},
            {"weight": 100, "rir": 1.0},
            {"weight": 100, "rir": 0.5},
        ]
    }
    # Recovery is poor: RHR 60 vs baseline 50
    metrics = make_metrics(60, 400, 7)
    baseline = make_metrics(50, 400, settings.BASELINE_DAYS)
    dal = DummyDal(lift_history, metrics, baseline)
    week = make_week()

    adjusted, notes = apply_progression(dal, week, None)
    weight = adjusted["days"][0]["sessions"][0]["exercises"][0]["weight_target"]
    assert weight == 103.75
    assert any("recovery poor" in n for n in notes)

def test_missing_history_keeps_target():
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
    dal = DummyDal(lift_history, metrics, baseline)
    week = make_week(target=50, ex_id=2)

    adjusted, notes = apply_progression(dal, week, None)
    weight = adjusted["days"][0]["sessions"][0]["exercises"][0]["weight_target"]
    assert weight == 50
    assert any("no history" in n for n in notes)

def test_no_rir_uses_weight_and_recovery():
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
    dal = DummyDal(lift_history, metrics, baseline)
    week = make_week()

    adjusted, notes = apply_progression(dal, week, None)
    weight = adjusted["days"][0]["sessions"][0]["exercises"][0]["weight_target"]
    assert weight == 105.0
    assert any("no RIR" in n for n in notes)

