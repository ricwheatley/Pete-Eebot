# pete_e/domain/schedule_rules.py
"""
Centralised 5/3/1 scheduling parameters.

This module defines the day split, set prescriptions, assistance pools, and any
derived annotations (e.g. rest guidance) so the builders and export logic stay
in lockstep with the published template.
"""

from __future__ import annotations

from datetime import time
from typing import Dict, List

# ------------------------------------------------------------------------------
# Exercise identifiers
# ------------------------------------------------------------------------------
# Big Four exercise IDs from the seeded wger catalogue
SQUAT_ID = 615
BENCH_ID = 73
DEADLIFT_ID = 184
OHP_ID = 566

# Mapping of main lift exercise IDs to plan builder lift codes
LIFT_CODE_BY_ID = {
    SQUAT_ID: "squat",
    BENCH_ID: "bench",
    DEADLIFT_ID: "deadlift",
    OHP_ID: "ohp",
}

MAIN_LIFT_IDS: tuple[int, ...] = tuple(LIFT_CODE_BY_ID.keys())

# Blaze is a fixed HIIT class logged as this id
BLAZE_ID = 1630

# Blaze class start times by weekday (1=Mon ... 7=Sun)
BLAZE_TIMES = {
    1: time(6, 15),  # Mon
    2: time(7, 0),   # Tue
    3: time(7, 0),   # Wed
    4: time(6, 15),  # Thu
    5: time(7, 15),  # Fri
}

# We treat Blaze duration as 45 minutes. We only store start time in DB.
BLAZE_DURATION_MIN = 45

# ------------------------------------------------------------------------------
# Week structure & timing
# ------------------------------------------------------------------------------
# Your lifting preference:
# - On Blaze-first days (Mon, Thu) we lift after Blaze.
# - On Weights-first days (Tue, Fri) we lift before Blaze.
def weight_slot_for_day(dow: int) -> time | None:
    """Return the scheduled start time for weights on the given weekday (1..7)."""

    if dow == 1:   # Mon, Blaze 06:15 -> weights 07:05
        return time(7, 5)
    if dow == 2:   # Tue, weights first 06:00
        return time(6, 0)
    if dow == 4:   # Thu, Blaze 06:15 -> weights 07:05
        return time(7, 5)
    if dow == 5:   # Fri, weights first 06:00
        return time(6, 0)
    return None  # No lifting on Wed/Sat/Sun


# Main lift mapping per weekday
MAIN_LIFT_BY_DOW = {
    1: BENCH_ID,   # Mon
    2: SQUAT_ID,   # Tue
    4: OHP_ID,     # Thu
    5: DEADLIFT_ID # Fri
}

# ------------------------------------------------------------------------------
# 5/3/1 prescriptions
# ------------------------------------------------------------------------------
_FIVE_THREE_ONE_TEMPLATE: Dict[int, Dict[str, object]] = {
    1: {
        "name": "Week 1 – 5s PRO",
        "main_sets": [
            {"percent": 50.0, "reps": 5, "rir": 5.0},
            {"percent": 55.0, "reps": 5, "rir": 5.0},
            {"percent": 60.0, "reps": 5, "rir": 5.0},
            {"percent": 65.0, "reps": 5, "rir": 3.0},
            {"percent": 75.0, "reps": 5, "rir": 2.0},
            {"percent": 85.0, "reps": 5, "rir": 0.0, "amrap": True},
        ],
        "rest_seconds": {"main": 150, "assistance": 75, "core": 45},
    },
    2: {
        "name": "Week 2 – 3s PRO",
        "main_sets": [
            {"percent": 55.0, "reps": 5, "rir": 5.0},
            {"percent": 60.0, "reps": 5, "rir": 5.0},
            {"percent": 65.0, "reps": 5, "rir": 5.0},
            {"percent": 70.0, "reps": 3, "rir": 3.0},
            {"percent": 80.0, "reps": 3, "rir": 2.0},
            {"percent": 90.0, "reps": 3, "rir": 0.0, "amrap": True},
        ],
        "rest_seconds": {"main": 165, "assistance": 90, "core": 60},
    },
    3: {
        "name": "Week 3 – 5/3/1",
        "main_sets": [
            {"percent": 60.0, "reps": 5, "rir": 5.0},
            {"percent": 65.0, "reps": 5, "rir": 5.0},
            {"percent": 70.0, "reps": 5, "rir": 5.0},
            {"percent": 75.0, "reps": 5, "rir": 3.0},
            {"percent": 85.0, "reps": 3, "rir": 2.0},
            {"percent": 95.0, "reps": 1, "rir": 0.0, "amrap": True},
        ],
        "rest_seconds": {"main": 180, "assistance": 105, "core": 75},
    },
    4: {
        "name": "Week 4 – Deload",
        "main_sets": [
            {"percent": 40.0, "reps": 5, "rir": 4.0},
            {"percent": 50.0, "reps": 5, "rir": 4.0},
            {"percent": 60.0, "reps": 5, "rir": 4.0},
        ],
        "rest_seconds": {"main": 90, "assistance": 60, "core": 45},
    },
}


def _normalise_week_number(week_number: int) -> int:
    return week_number if week_number in _FIVE_THREE_ONE_TEMPLATE else 1


def get_main_set_scheme(week_number: int) -> List[Dict[str, float]]:
    """Return the ordered set prescriptions for the requested week."""

    template = _FIVE_THREE_ONE_TEMPLATE[_normalise_week_number(week_number)]
    return [dict(item) for item in template["main_sets"]]  # defensive copy


def main_set_summary(week_number: int) -> Dict[str, float]:
    """Legacy accessor approximating the top set characteristics."""

    sets = get_main_set_scheme(week_number)
    top_set = sets[-1]
    return {
        "sets": len(sets),
        "reps": top_set["reps"],
        "percent_1rm": top_set["percent"],
        "rir_cue": top_set.get("rir", 0.0),
    }


def rest_seconds_for(role: str, week_number: int) -> int:
    """Return the programmed rest interval for the supplied role."""

    role_key = role.lower()
    template = _FIVE_THREE_ONE_TEMPLATE[_normalise_week_number(week_number)]
    rest_map = template["rest_seconds"]
    assert isinstance(rest_map, dict)
    return int(rest_map.get(role_key, 60))


def describe_main_set(
    *,
    week_number: int,
    set_index: int,
    percent: float | None,
    reps: int | None,
) -> str:
    scheme = get_main_set_scheme(week_number)
    idx = max(1, min(set_index, len(scheme))) - 1
    entry = scheme[idx]
    set_percent = percent if percent is not None else entry["percent"]
    set_reps = reps if reps is not None else entry["reps"]
    tag = "AMRAP" if entry.get("amrap") else f"{int(set_reps)} reps"
    return f"{entry.get('label') or f'Set {set_index}'} @ {set_percent:.0f}% TM ({tag})"


def describe_assistance(sets: int | None, reps: int | None) -> str:
    return f"Assistance {sets or 3} x {reps or 10}"


def describe_core(sets: int | None, reps: int | None) -> str:
    return f"Core {sets or 3} x {reps or 12}"


def format_rest_seconds(seconds: int | None) -> str | None:
    if not seconds:
        return None
    minutes, secs = divmod(seconds, 60)
    if minutes and secs:
        return f"Rest {minutes}m {secs}s"
    if minutes:
        return f"Rest {minutes}m"
    return f"Rest {secs}s"


# ------------------------------------------------------------------------------
# Assistance & core pools
# ------------------------------------------------------------------------------
ASSISTANCE_POOL_DATA: List[tuple[int, List[int]]] = [
    (
        BENCH_ID,
        [
            81,   # Bent Over Dumbbell Rows
            76,   # Bench Press Narrow Grip
            194,  # Dips
            512,  # Seated Row (narrow grip)
            137,  # Butterfly Narrow Grip
        ],
    ),
    (
        SQUAT_ID,
        [
            43,    # Barbell Hack Squats
            46,    # Barbell Lunges Standing
            373,   # Leg Press narrow
            988,   # Bulgarian split squat (left)
            1366,  # Dumbbell Split Squat
        ],
    ),
    (
        OHP_ID,
        [
            20,   # Arnold Shoulder Press
            82,   # Bent-over Lateral Raises
            394,  # Low Row (long pulley)
            448,  # Pendlay Rows
            512,  # Seated Row, narrow grip
        ],
    ),
    (
        DEADLIFT_ID,
        [
            507,  # Romanian Deadlift
            268,  # Good Mornings
            265,  # Glute Bridge
            294,  # Hip Thrust
            1348, # Lower Back Extensions
        ],
    ),
]

_ASSISTANCE_FALLBACK: Dict[int, List[int]] = {main: assists for main, assists in ASSISTANCE_POOL_DATA}

DEFAULT_CORE_POOL_IDS: List[int] = [458, 500, 580, 1001, 1410]


def default_assistance_for(main_lift_id: int) -> List[int]:
    return list(_ASSISTANCE_FALLBACK.get(main_lift_id, []))


def classify_exercise(exercise_id: int | None) -> str:
    if exercise_id is None:
        return "other"
    if exercise_id == BLAZE_ID:
        return "cardio"
    if exercise_id in MAIN_LIFT_IDS:
        return "main"
    if exercise_id in DEFAULT_CORE_POOL_IDS:
        return "core"
    return "assistance"


# Assistance prescriptions
ASSISTANCE_1 = {"sets": 3, "reps_low": 10, "reps_high": 12, "rir_cue": 2.0}
ASSISTANCE_2 = {"sets": 3, "reps_low": 8,  "reps_high": 10, "rir_cue": 2.0}

# Core prescriptions (rep or time envelope, we store reps here)
CORE_SCHEME = {"sets": 3, "reps_low": 10, "reps_high": 15, "rir_cue": 2.0}

# ------------------------------------------------------------------------------
# Strength test configuration
# ------------------------------------------------------------------------------
TEST_WEEK_LIFT_ORDER = [
    BENCH_ID,
    SQUAT_ID,
    OHP_ID,
    DEADLIFT_ID,
]

TEST_WEEK_PCTS = {
    BENCH_ID: 85.0,
    SQUAT_ID: 87.5,
    OHP_ID: 85.0,
    DEADLIFT_ID: 90.0,
}
