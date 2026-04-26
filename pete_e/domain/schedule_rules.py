# pete_e/domain/schedule_rules.py
"""
Centralised 5/3/1 scheduling parameters.

This module defines the day split, set prescriptions, assistance pools, and any
derived annotations (e.g. rest guidance) so the builders and export logic stay
in lockstep with the published template.
"""

from __future__ import annotations

from datetime import time
from typing import Any, Dict, List, Mapping

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

# Running exercise IDs from the seeded wger catalogue.
TREADMILL_RUN_ID = 530
OUTDOOR_RUN_ID = 527
RUN_CARDIO_EXERCISE_ID = TREADMILL_RUN_ID

RUN_SESSION_TYPES = {
    "intervals",
    "tempo",
    "easy",
    "steady",
    "recovery",
    "long_run",
}

STRETCH_SESSION_TYPE = "stretch_routine"
MOBILITY_WORKOUT_TYPE = "mobility"

# Blaze class start times by weekday (1=Mon ... 7=Sun)
BLAZE_TIMES = {
#    1: time(6, 15),  # Mon
#    2: time(7, 0),   # Tue
#    3: time(7, 0),   # Wed
#    4: time(6, 15),  # Thu
#    5: time(7, 15),  # Fri
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

# Mobility / stretch routines are layered onto training days after the main work.
# Edit the mapping or the routine definitions below to add/remove work per day.
TRAINING_DAY_STRETCH_ROUTINE_BY_DOW = {
    1: "limber_11",
    2: "limber_11",
    4: "limber_11",
    5: "limber_11",
    6: "limber_11",
}

# ------------------------------------------------------------------------------
# 5/3/1 prescriptions
# ------------------------------------------------------------------------------
_FIVE_THREE_ONE_TEMPLATE: Dict[int, Dict[str, object]] = {
    1: {
        "name": "Week 1 – 5s PRO",
        "main_sets": [
            {"percent": 50.0, "reps": 5},
            {"percent": 55.0, "reps": 5},
            {"percent": 60.0, "reps": 5},
            {"percent": 65.0, "reps": 5, "rir": 3.0},
            {"percent": 75.0, "reps": 5, "rir": 2.0},
            {"percent": 85.0, "reps": 5, "rir": 0.0, "amrap": True},
        ],
        "rest_seconds": {"main": 150, "assistance": 75, "core": 45},
    },
    2: {
        "name": "Week 2 – 3s PRO",
        "main_sets": [
            {"percent": 55.0, "reps": 5},
            {"percent": 60.0, "reps": 5},
            {"percent": 65.0, "reps": 5},
            {"percent": 70.0, "reps": 3, "rir": 3.0},
            {"percent": 80.0, "reps": 3, "rir": 2.0},
            {"percent": 90.0, "reps": 3, "rir": 0.0, "amrap": True},
        ],
        "rest_seconds": {"main": 165, "assistance": 90, "core": 60},
    },
    3: {
        "name": "Week 3 – 5/3/1",
        "main_sets": [
            {"percent": 60.0, "reps": 5},
            {"percent": 65.0, "reps": 5},
            {"percent": 70.0, "reps": 5},
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


def format_weight_kg(weight_kg: float | None) -> str | None:
    if weight_kg is None:
        return None
    rounded = round(float(weight_kg), 2)
    if rounded.is_integer():
        return f"{int(rounded)} kg"
    text = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return f"{text} kg"


def workout_display_order(
    *,
    is_cardio: bool,
    exercise_id: int | None = None,
    workout_type: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> int:
    """Return the intended within-day ordering for a session."""

    details_map = details if isinstance(details, Mapping) else {}
    session_type = str(details_map.get("session_type") or "").strip().lower()
    workout_kind = str(workout_type or "").strip().lower()

    if session_type in RUN_SESSION_TYPES:
        return 10
    if is_cardio:
        return 15
    if session_type == STRETCH_SESSION_TYPE or workout_kind == MOBILITY_WORKOUT_TYPE:
        return 30

    role = classify_exercise(exercise_id)
    if role == "main":
        return 20
    if role in {"assistance", "core"}:
        return 25
    return 20


def _clean_number_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.1f}".rstrip("0").rstrip(".")


def _speed_range_text(step: Mapping[str, Any]) -> str | None:
    minimum = _clean_number_text(step.get("min_speed_kph"))
    maximum = _clean_number_text(step.get("max_speed_kph"))
    exact = _clean_number_text(step.get("speed_kph"))

    if minimum and maximum:
        return f"{minimum}-{maximum} km/h"
    if exact:
        return f"{exact} km/h"
    return None


def running_session_summary(details: Mapping[str, Any] | None) -> str | None:
    details_map = details if isinstance(details, Mapping) else {}
    session_type = str(details_map.get("session_type") or "").strip().lower()
    steps = details_map.get("steps")
    if session_type not in RUN_SESSION_TYPES or not isinstance(steps, list):
        return None

    if session_type == "intervals" and len(steps) >= 3:
        warmup = steps[0] if isinstance(steps[0], Mapping) else {}
        repeat = steps[1] if isinstance(steps[1], Mapping) else {}
        cooldown = steps[2] if isinstance(steps[2], Mapping) else {}
        repeat_steps = repeat.get("steps") if isinstance(repeat, Mapping) else None
        work = repeat_steps[0] if isinstance(repeat_steps, list) and len(repeat_steps) > 0 and isinstance(repeat_steps[0], Mapping) else {}
        recovery = repeat_steps[1] if isinstance(repeat_steps, list) and len(repeat_steps) > 1 and isinstance(repeat_steps[1], Mapping) else {}
        repeats = _clean_number_text(repeat.get("repeats"))
        work_duration = _clean_number_text(work.get("duration_minutes"))
        work_speed = _clean_number_text(work.get("speed_kph"))
        recovery_duration = _clean_number_text(recovery.get("duration_minutes"))
        recovery_speed = _clean_number_text(recovery.get("speed_kph"))
        warmup_duration = _clean_number_text(warmup.get("duration_minutes"))
        cooldown_duration = _clean_number_text(cooldown.get("duration_minutes"))
        if all((repeats, work_duration, work_speed, recovery_duration, recovery_speed, warmup_duration, cooldown_duration)):
            return (
                f"Intervals {repeats} x ({work_duration}m @ {work_speed} km/h, "
                f"{recovery_duration}m @ {recovery_speed} km/h) after "
                f"{warmup_duration}m warmup and {cooldown_duration}m cooldown"
            )

    if session_type == "tempo" and len(steps) >= 3:
        warmup = steps[0] if isinstance(steps[0], Mapping) else {}
        steady = steps[1] if isinstance(steps[1], Mapping) else {}
        cooldown = steps[2] if isinstance(steps[2], Mapping) else {}
        warmup_duration = _clean_number_text(warmup.get("duration_minutes"))
        steady_duration = _clean_number_text(steady.get("duration_minutes"))
        steady_speed = _clean_number_text(steady.get("speed_kph"))
        cooldown_duration = _clean_number_text(cooldown.get("duration_minutes"))
        if all((warmup_duration, steady_duration, steady_speed, cooldown_duration)):
            return (
                f"Tempo {steady_duration}m @ {steady_speed} km/h after "
                f"{warmup_duration}m warmup and {cooldown_duration}m cooldown"
            )

    if session_type in {"easy", "steady", "recovery"} and steps:
        first = steps[0] if isinstance(steps[0], Mapping) else {}
        duration = _clean_number_text(first.get("duration_minutes"))
        min_duration = _clean_number_text(first.get("min_duration_minutes"))
        max_duration = _clean_number_text(first.get("max_duration_minutes"))
        speed = _speed_range_text(first)
        label = {
            "easy": "Easy run",
            "steady": "Steady run",
            "recovery": "Recovery run",
        }[session_type]
        duration_text = None
        if duration:
            duration_text = f"{duration}m"
        elif min_duration and max_duration:
            duration_text = f"{min_duration}-{max_duration}m"
        if duration_text and speed:
            return f"{label} {duration_text} @ {speed}"

    if session_type == "long_run" and steps:
        first = steps[0] if isinstance(steps[0], Mapping) else {}
        distance = _clean_number_text(first.get("distance_km"))
        speed = _speed_range_text(first)
        if distance and speed:
            return f"Long run {distance} km @ {speed}"
        if distance:
            return f"Long run {distance} km"

    label = {
        "intervals": "Intervals",
        "tempo": "Tempo run",
        "easy": "Easy run",
        "steady": "Steady run",
        "recovery": "Recovery run",
        "long_run": "Long run",
    }.get(session_type)
    return label


def _stretch_step_label(step: Mapping[str, Any]) -> str | None:
    name = str(step.get("name") or "").strip()
    if not name:
        return None
    if step.get("is_isometric"):
        return f"{name} [isometric]"
    if step.get("includes_isometric_hold"):
        hold_seconds = _clean_number_text(step.get("hold_seconds"))
        if hold_seconds:
            return f"{name} [dynamic + {hold_seconds}s hold]"
        return f"{name} [dynamic + hold]"
    movement_type = str(step.get("movement_type") or "").strip()
    if movement_type:
        return f"{name} [{movement_type}]"
    return name


def stretch_routine_summary(details: Mapping[str, Any] | None) -> str | None:
    details_map = details if isinstance(details, Mapping) else {}
    if str(details_map.get("session_type") or "").strip().lower() != STRETCH_SESSION_TYPE:
        return None

    display_name = str(details_map.get("display_name") or "Stretch routine").strip()
    steps = details_map.get("steps")
    if not isinstance(steps, list) or not steps:
        return display_name

    step_count = len(steps)
    isometric_step = next(
        (
            step
            for step in steps
            if isinstance(step, Mapping) and step.get("is_isometric")
        ),
        None,
    )
    mixed_hold_step = next(
        (
            step
            for step in steps
            if isinstance(step, Mapping) and step.get("includes_isometric_hold")
        ),
        None,
    )

    snippets: List[str] = [f"{step_count}-step mobility flow"]
    if isinstance(isometric_step, Mapping):
        label = _stretch_step_label(isometric_step)
        if label:
            snippets.append(label)
    if isinstance(mixed_hold_step, Mapping):
        label = _stretch_step_label(mixed_hold_step)
        if label:
            snippets.append(label)
    return f"{display_name}: " + "; ".join(snippets)


def stretch_routine_description(details: Mapping[str, Any] | None) -> str:
    details_map = details if isinstance(details, Mapping) else {}
    display_name = str(details_map.get("display_name") or "Stretch routine").strip()
    source = str(details_map.get("source") or "").strip()
    steps = details_map.get("steps")

    lines: List[str] = [display_name]
    if source:
        lines.append(f"Source: {source}")

    if isinstance(steps, list) and steps:
        lines.append("")
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, Mapping):
                continue
            label = _stretch_step_label(step)
            prescription = str(step.get("prescription") or "").strip()
            if label and prescription:
                lines.append(f"{index}. {label} - {prescription}")
            elif label:
                lines.append(f"{index}. {label}")

    return "\n".join(lines).strip()


def build_export_comment(
    *,
    base_comment: str | None,
    details: Mapping[str, Any] | None,
) -> str | None:
    comment = str(base_comment or "").strip()
    details_map = details if isinstance(details, Mapping) else None
    if details_map is None:
        return comment or None

    run_summary = running_session_summary(details_map)
    if run_summary:
        return f"{comment}: {run_summary}" if comment else run_summary

    stretch_summary = stretch_routine_summary(details_map)
    if stretch_summary:
        if comment and stretch_summary.lower().startswith(comment.lower()):
            return stretch_summary
        return f"{comment}: {stretch_summary}" if comment else stretch_summary

    return comment or None


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
    if exercise_id in {BLAZE_ID, TREADMILL_RUN_ID, OUTDOOR_RUN_ID}:
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
# Mobility / stretch routines
# ------------------------------------------------------------------------------
LIMBER_11_STEPS: List[Dict[str, Any]] = [
    {
        "name": "Foam Roll IT Band",
        "prescription": "10-15 passes",
        "movement_type": "soft_tissue",
        "is_isometric": False,
    },
    {
        "name": "Foam Roll Adductors",
        "prescription": "10-15 passes",
        "movement_type": "soft_tissue",
        "is_isometric": False,
    },
    {
        "name": "SMR Glutes (lax ball)",
        "prescription": "30 sec-2 min",
        "movement_type": "soft_tissue",
        "is_isometric": False,
    },
    {
        "name": "Bent-knee Iron Cross",
        "prescription": "5-10 reps each side",
        "movement_type": "dynamic",
        "is_isometric": False,
    },
    {
        "name": "Roll-overs into V-sits",
        "prescription": "10 reps",
        "movement_type": "dynamic",
        "is_isometric": False,
    },
    {
        "name": "Rocking Frog Stretch",
        "prescription": "10 reps",
        "movement_type": "dynamic",
        "is_isometric": False,
    },
    {
        "name": "Fire Hydrant Circles",
        "prescription": "10 forward / 10 backward",
        "movement_type": "dynamic",
        "is_isometric": False,
    },
    {
        "name": "Mountain Climbers",
        "prescription": "10 reps each leg",
        "movement_type": "dynamic",
        "is_isometric": False,
    },
    {
        "name": "Cossack Squats",
        "prescription": "5-10 reps each side",
        "movement_type": "dynamic",
        "is_isometric": False,
    },
    {
        "name": "Seated Piriformis Stretch",
        "prescription": "20-30 sec each side",
        "movement_type": "static",
        "is_isometric": True,
    },
    {
        "name": "Rear-foot-elevated Hip Flexor Stretch",
        "prescription": "5-10 reps each side",
        "movement_type": "dynamic",
        "is_isometric": False,
        "includes_isometric_hold": True,
        "hold_seconds": 3,
    },
]

STRETCH_ROUTINES: Dict[str, Dict[str, Any]] = {
    "limber_11": {
        "display_name": "Limber 11",
        "source": "Joe DeFranco",
        "estimated_duration_min": 15,
        "sequence_order": 30,
        "steps": LIMBER_11_STEPS,
    }
}


def build_stretch_routine_details(routine_key: str) -> Dict[str, Any] | None:
    """Return a copy of the configured stretch routine details."""

    routine = STRETCH_ROUTINES.get(routine_key)
    if not routine:
        return None

    return {
        "session_type": STRETCH_SESSION_TYPE,
        "routine_key": routine_key,
        "display_name": routine["display_name"],
        "source": routine.get("source"),
        "estimated_duration_min": routine.get("estimated_duration_min"),
        "sequence_order": routine.get("sequence_order", 30),
        "steps": [dict(step) for step in routine.get("steps", [])],
    }


def stretch_routine_for_day(dow: int) -> Dict[str, Any] | None:
    """Return the stretch routine configured for a weekday, if any."""

    routine_key = TRAINING_DAY_STRETCH_ROUTINE_BY_DOW.get(dow)
    if not routine_key:
        return None
    return build_stretch_routine_details(routine_key)

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

# ------------------------------------------------------------------------------
# Treadmill running prescriptions
# ------------------------------------------------------------------------------
TREADMILL_DEFAULT_INCLINE_PERCENT = 0.0
TREADMILL_OPTIONAL_INCLINE_HINT = "Optional: use 1% incline to mimic outdoor feel."
ANCHOR_5K_PACE_KPH = 10.0


def _base_running_details(session_type: str) -> Dict[str, Any]:
    return {
        "session_type": session_type,
        "sequence_order": 10,
        "treadmill": True,
        "incline_percent": TREADMILL_DEFAULT_INCLINE_PERCENT,
        "anchor_pace_kph": ANCHOR_5K_PACE_KPH,
        "incline_hint": TREADMILL_OPTIONAL_INCLINE_HINT,
    }


def quality_intervals_details() -> Dict[str, Any]:
    details = _base_running_details("intervals")
    details["steps"] = [
        {"kind": "warmup", "duration_minutes": 5, "speed_kph": 8.5},
        {
            "kind": "repeat",
            "repeats": 5,
            "steps": [
                {"kind": "work", "duration_minutes": 3, "speed_kph": 11.5},
                {"kind": "recovery", "duration_minutes": 2, "speed_kph": 8.5},
            ],
        },
        {"kind": "cooldown", "duration_minutes": 5, "speed_kph": 8.5},
    ]
    return details


def quality_tempo_details() -> Dict[str, Any]:
    details = _base_running_details("tempo")
    details["steps"] = [
        {"kind": "warmup", "duration_minutes": 5, "speed_kph": 8.5},
        {"kind": "steady", "duration_minutes": 20, "speed_kph": 10.5},
        {"kind": "cooldown", "duration_minutes": 5, "speed_kph": 8.5},
    ]
    return details


def easy_run_details(
    *,
    duration_minutes: int = 20,
    speed_kph: float = 8.9,
    min_speed_kph: float | None = 8.8,
    max_speed_kph: float | None = 9.0,
) -> Dict[str, Any]:
    details = _base_running_details("easy")
    details["steps"] = [
        {
            "kind": "steady",
            "duration_minutes": duration_minutes,
            "speed_kph": speed_kph,
            "min_speed_kph": min_speed_kph,
            "max_speed_kph": max_speed_kph,
        }
    ]
    return details


def steady_run_details(
    *,
    duration_minutes: int = 35,
    speed_kph: float = 9.9,
    min_speed_kph: float | None = 9.8,
    max_speed_kph: float | None = 10.0,
) -> Dict[str, Any]:
    details = _base_running_details("steady")
    details["steps"] = [
        {
            "kind": "steady",
            "duration_minutes": duration_minutes,
            "speed_kph": speed_kph,
            "min_speed_kph": min_speed_kph,
            "max_speed_kph": max_speed_kph,
        }
    ]
    return details


def recovery_micro_run_details(
    *,
    duration_minutes: int = 12,
    speed_kph: float = 8.5,
) -> Dict[str, Any]:
    details = _base_running_details("recovery")
    details["steps"] = [
        {
            "kind": "steady",
            "duration_minutes": duration_minutes,
            "min_duration_minutes": 10,
            "max_duration_minutes": 15,
            "speed_kph": speed_kph,
        }
    ]
    return details


def long_run_details(
    *,
    distance_km: int,
    speed_kph: float = 9.0,
    min_speed_kph: float | None = 8.8,
    max_speed_kph: float | None = 9.2,
) -> Dict[str, Any]:
    details = _base_running_details("long_run")
    details["steps"] = [
        {
            "kind": "long_run",
            "distance_km": distance_km,
            "speed_kph": speed_kph,
            "min_speed_kph": min_speed_kph,
            "max_speed_kph": max_speed_kph,
        }
    ]
    details["progression"] = {
        "start_distance_km": distance_km,
        "weekly_increment_km": 1,
        "cap_distance_km": None,
    }
    return details
