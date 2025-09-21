from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pete_e.config import settings
from pete_e.domain.data_access import DataAccessLayer
from pete_e.domain.validation import ensure_muscle_balance

INTENSITY_SEQUENCE: Tuple[str, ...] = ("light", "medium", "heavy", "deload")
INTENSITY_SETTINGS: Dict[str, Dict[str, Any]] = {
    "light": {"set_multiplier": 0.85, "rir_adjust": 1, "rep_bias": "high"},
    "medium": {"set_multiplier": 1.0, "rir_adjust": 0, "rep_bias": "mid"},
    "heavy": {"set_multiplier": 1.15, "rir_adjust": -1, "rep_bias": "low"},
    "deload": {"set_multiplier": 0.60, "rir_adjust": 1, "rep_bias": "high"},
}


@dataclass(frozen=True)
class SessionSlot:
    pool: str
    slot: str
    base_sets: int
    reps_low: int
    reps_high: int
    base_rir: Optional[int]
    min_sets: int = 1


EXERCISE_POOLS: Dict[str, Tuple[Dict[str, Any], ...]] = {
    "push_compound": (
        {"id": 1001, "muscle_group": "upper_push"},
        {"id": 1002, "muscle_group": "upper_push"},
        {"id": 1003, "muscle_group": "upper_push"},
        {"id": 1004, "muscle_group": "upper_push"},
    ),
    "push_accessory": (
        {"id": 1101, "muscle_group": "upper_push"},
        {"id": 1102, "muscle_group": "upper_push"},
        {"id": 1103, "muscle_group": "upper_push"},
        {"id": 1104, "muscle_group": "upper_push"},
    ),
    "pull_compound": (
        {"id": 2001, "muscle_group": "upper_pull"},
        {"id": 2002, "muscle_group": "upper_pull"},
        {"id": 2003, "muscle_group": "upper_pull"},
        {"id": 2004, "muscle_group": "upper_pull"},
    ),
    "pull_accessory": (
        {"id": 2101, "muscle_group": "upper_pull"},
        {"id": 2102, "muscle_group": "upper_pull"},
        {"id": 2103, "muscle_group": "upper_pull"},
        {"id": 2104, "muscle_group": "upper_pull"},
    ),
    "lower_compound": (
        {"id": 3001, "muscle_group": "lower"},
        {"id": 3002, "muscle_group": "lower"},
        {"id": 3003, "muscle_group": "lower"},
        {"id": 3004, "muscle_group": "lower"},
    ),
    "lower_accessory": (
        {"id": 3101, "muscle_group": "lower"},
        {"id": 3102, "muscle_group": "lower"},
        {"id": 3103, "muscle_group": "lower"},
        {"id": 3104, "muscle_group": "lower"},
    ),
    "core": (
        {"id": 5001, "muscle_group": "core"},
        {"id": 5002, "muscle_group": "core"},
        {"id": 5003, "muscle_group": "core"},
        {"id": 5004, "muscle_group": "core"},
    ),
    "conditioning": (
        {"id": 6001, "muscle_group": "conditioning"},
        {"id": 6002, "muscle_group": "conditioning"},
        {"id": 6003, "muscle_group": "conditioning"},
        {"id": 6004, "muscle_group": "conditioning"},
    ),
}

SESSION_BLUEPRINT: Tuple[Dict[str, Any], ...] = (
    {
        "day_of_week": 1,
        "focus": "upper_push",
        "slots": (
            SessionSlot("push_compound", "main", 4, 6, 8, 2, min_sets=2),
            SessionSlot("push_accessory", "secondary", 3, 10, 12, 2),
            SessionSlot("core", "auxiliary", 3, 12, 15, 3),
        ),
    },
    {
        "day_of_week": 3,
        "focus": "lower",
        "slots": (
            SessionSlot("lower_compound", "main", 4, 6, 9, 2, min_sets=2),
            SessionSlot("lower_accessory", "secondary", 3, 8, 12, 2),
            SessionSlot("core", "auxiliary", 3, 10, 15, 3),
        ),
    },
    {
        "day_of_week": 5,
        "focus": "upper_pull",
        "slots": (
            SessionSlot("pull_compound", "main", 4, 6, 8, 2, min_sets=2),
            SessionSlot("pull_accessory", "secondary", 3, 8, 12, 2),
            SessionSlot("core", "auxiliary", 3, 12, 15, 3),
        ),
    },
    {
        "day_of_week": 6,
        "focus": "conditioning",
        "slots": (
            SessionSlot("conditioning", "conditioning", 1, 1, 1, None, min_sets=1),
        ),
    },
)


def _mean_metric(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
    values: List[float] = []
    for row in rows:
        value = row.get(key)
        if not value:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return sum(values) / len(values)


def _prefer_lighter_weeks(metrics: List[Dict[str, Any]]) -> bool:
    avg_sleep = _mean_metric(metrics, "sleep_asleep_minutes")
    avg_rhr = _mean_metric(metrics, "hr_resting")

    sleep_threshold = getattr(settings, "RECOVERY_SLEEP_THRESHOLD_MINUTES", None)
    rhr_threshold = getattr(settings, "RECOVERY_RHR_THRESHOLD", None)

    prefer_light = False
    if sleep_threshold and avg_sleep is not None and avg_sleep < float(sleep_threshold):
        prefer_light = True
    if rhr_threshold and avg_rhr is not None and avg_rhr > float(rhr_threshold):
        prefer_light = True
    return prefer_light


def _initial_pool_offsets(start_date: date) -> Dict[str, int]:
    seed = start_date.toordinal()
    offsets: Dict[str, int] = {}
    for name, pool in EXERCISE_POOLS.items():
        if not pool:
            raise ValueError(f"Exercise pool '{name}' has no exercises configured")
        offsets[name] = seed % len(pool)
        seed = (seed // 7) + 1
    return offsets


def _pull_exercise(pool_name: str, offsets: Dict[str, int]) -> Dict[str, Any]:
    pool = EXERCISE_POOLS[pool_name]
    index = offsets[pool_name]
    exercise = pool[index]
    offsets[pool_name] = (index + 1) % len(pool)
    return exercise


def _scaled_sets(slot: SessionSlot, multiplier: float) -> int:
    scaled = round(slot.base_sets * multiplier)
    min_sets = max(1, slot.min_sets)
    return max(min_sets, int(scaled))


def _select_reps(slot: SessionSlot, bias: str) -> int:
    low, high = slot.reps_low, slot.reps_high
    if low == high:
        return low
    if bias == "low":
        return low
    if bias == "high":
        return high
    return int(round((low + high) / 2))


def _intensity_params(intensity: str, prefer_light: bool) -> Tuple[float, int, str]:
    base = INTENSITY_SETTINGS[intensity]
    set_multiplier = float(base["set_multiplier"])
    rir_adjust = int(base["rir_adjust"])
    rep_bias = str(base["rep_bias"])

    if prefer_light:
        if intensity == "light":
            set_multiplier *= 0.90
        elif intensity == "medium":
            set_multiplier *= 0.95
        elif intensity == "heavy":
            set_multiplier *= 1.00
        rir_adjust += 1
        if rep_bias == "low":
            rep_bias = "mid"
    return set_multiplier, rir_adjust, rep_bias


def _resolve_rir(slot: SessionSlot, rir_adjust: int) -> Optional[int]:
    if slot.base_rir is None:
        return None
    rir_value = slot.base_rir + rir_adjust
    return max(0, min(4, rir_value))


def build_block(dal: DataAccessLayer, start_date: date, weeks: int = 4) -> int:
    if weeks != len(INTENSITY_SEQUENCE):
        raise ValueError("plan_builder only supports 4-week blocks")

    lookup_existing = getattr(dal, "find_plan_by_start_date", None)
    if callable(lookup_existing):
        try:
            existing = lookup_existing(start_date)
        except Exception:
            existing = None
        if isinstance(existing, dict) and existing.get("id") is not None:
            return int(existing["id"])

    recent_metrics = dal.get_historical_metrics(7)
    if not recent_metrics:
        raise RuntimeError("No historical metrics available to seed plan building")

    prefer_light = _prefer_lighter_weeks(recent_metrics)
    pool_offsets = _initial_pool_offsets(start_date)

    weeks_out: List[Dict[str, Any]] = []
    for week_index, intensity in enumerate(INTENSITY_SEQUENCE, start=1):
        set_multiplier, rir_adjust, rep_bias = _intensity_params(intensity, prefer_light)
        week_workouts: List[Dict[str, Any]] = []
        week_start = start_date + timedelta(days=(week_index - 1) * 7)

        for session in SESSION_BLUEPRINT:
            focus = session["focus"]
            day_of_week = session["day_of_week"]

            for slot in session["slots"]:
                exercise = _pull_exercise(slot.pool, pool_offsets)

                slot_multiplier = set_multiplier
                if slot.slot == "auxiliary":
                    slot_multiplier *= 0.9
                elif slot.slot == "conditioning":
                    slot_multiplier = 1.0

                sets = _scaled_sets(slot, slot_multiplier)
                slot_bias = rep_bias
                if slot.slot != "main" and rep_bias == "low":
                    slot_bias = "mid"
                reps = _select_reps(slot, slot_bias)
                rir = _resolve_rir(slot, rir_adjust)

                workout = {
                    "day_of_week": day_of_week,
                    "exercise_id": exercise["id"],
                    "sets": sets,
                    "reps": reps,
                    "rir": rir,
                    "focus": focus,
                    "slot": slot.slot,
                    "muscle_group": exercise["muscle_group"],
                    "intensity": intensity,
                }
                week_workouts.append(workout)

        weeks_out.append(
            {
                "week_number": week_index,
                "intensity": intensity,
                "start_date": week_start.isoformat(),
                "workouts": week_workouts,
            }
        )

    plan = {
        "weeks": weeks_out,
        "metadata": {"prefer_light": prefer_light},
    }

    balance_report = ensure_muscle_balance(plan)
    if not balance_report.balanced:
        raise RuntimeError(
            "Generated plan failed muscle balance validation: "
            f"volumes={balance_report.totals_by_group}, "
            f"missing={balance_report.missing_groups}"
        )

    plan_id = dal.save_training_plan(plan, start_date)
    if not plan_id:
        raise RuntimeError("Failed to persist training plan to database")

    return plan_id
