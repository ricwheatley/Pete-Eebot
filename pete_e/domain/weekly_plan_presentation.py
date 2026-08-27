"""Pure normalization and rendering for weekly workout plan presentation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast


DAY_NAMES: dict[int, str] = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}


class WorkoutDisplayOrder(Protocol):
    """Existing schedule policy used to order sessions within a day."""

    def __call__(
        self,
        *,
        is_cardio: bool,
        exercise_id: int | None = None,
        workout_type: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> int: ...


@dataclass(frozen=True)
class WeeklyPlanSession:
    """One normalized session, before compatibility text layout is applied."""

    day_number: int
    name: str
    details: tuple[str, ...]
    display_order: int
    source_position: int


@dataclass(frozen=True)
class WeeklyPlanDay:
    """One calendar day and its stably ordered sessions."""

    day_number: int
    name: str
    sessions: tuple[WeeklyPlanSession, ...]


@dataclass(frozen=True)
class WeeklyPlanPresentation:
    """All seven ordered days, retaining empty days as explicit rest metadata."""

    days: tuple[WeeklyPlanDay, ...]

    @property
    def rest_day_names(self) -> tuple[str, ...]:
        return tuple(day.name for day in self.days if not day.sessions)


def clean_number(raw: Any) -> str:
    """Preserve the weekly renderer's compact numeric representation."""

    try:
        value = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"


def clean_float(value: Any) -> str:
    """Preserve the weekly treadmill renderer's one-decimal representation."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.1f}"


def _step_at(steps: list[Any], index: int) -> Mapping[str, Any]:
    if index >= len(steps) or not isinstance(steps[index], Mapping):
        return {}
    return cast(Mapping[str, Any], steps[index])


def _render_intervals(steps: list[Any]) -> str:
    warmup = _step_at(steps, 0)
    repeat = _step_at(steps, 1)
    cooldown = _step_at(steps, 2)
    repeat_steps = repeat.get("steps")
    work: Any = (
        repeat_steps[0] if isinstance(repeat_steps, list) and repeat_steps else {}
    )
    recovery: Any = (
        repeat_steps[1]
        if isinstance(repeat_steps, list) and len(repeat_steps) > 1
        else {}
    )
    return (
        f"Warmup {clean_number(warmup.get('duration_minutes'))} min @ "
        f"{clean_float(warmup.get('speed_kph'))} km/h; "
        f"{clean_number(repeat.get('repeats'))} × "
        f"({clean_number(work.get('duration_minutes'))} min @ "
        f"{clean_float(work.get('speed_kph'))} km/h, "
        f"{clean_number(recovery.get('duration_minutes'))} min @ "
        f"{clean_float(recovery.get('speed_kph'))} km/h); "
        f"Cooldown {clean_number(cooldown.get('duration_minutes'))} min @ "
        f"{clean_float(cooldown.get('speed_kph'))} km/h"
    )


def _speed_range(step: Mapping[str, Any]) -> str | None:
    minimum = step.get("min_speed_kph")
    maximum = step.get("max_speed_kph")
    if minimum is None or maximum is None:
        return None
    return f"{clean_float(minimum)}–{clean_float(maximum)}"


def _render_tempo(steps: list[Any]) -> str:
    warmup = _step_at(steps, 0)
    main = _step_at(steps, 1)
    cooldown = _step_at(steps, 2)
    return (
        f"Warmup {clean_number(warmup.get('duration_minutes'))} min @ "
        f"{clean_float(warmup.get('speed_kph'))} km/h; "
        f"{clean_number(main.get('duration_minutes'))} min @ "
        f"{clean_float(main.get('speed_kph'))} km/h; "
        f"Cooldown {clean_number(cooldown.get('duration_minutes'))} min @ "
        f"{clean_float(cooldown.get('speed_kph'))} km/h"
    )


def _render_recovery(step: Mapping[str, Any], speed: str) -> str:
    minimum = step.get("min_duration_minutes")
    maximum = step.get("max_duration_minutes")
    if minimum is not None and maximum is not None:
        return f"{clean_number(minimum)}–{clean_number(maximum)} min @ {speed} km/h"
    return f"{clean_number(step.get('duration_minutes'))} min @ {speed} km/h"


def _render_non_interval(session_type: str, steps: list[Any]) -> str | None:
    step = _step_at(steps, 0)
    speed = clean_float(step.get("speed_kph"))
    speed_range = _speed_range(step)

    if session_type == "tempo":
        return _render_tempo(steps)
    if session_type in {"easy", "steady"}:
        label = session_type
        suffix = f" ({label} range {speed_range})" if speed_range else ""
        return (
            f"{clean_number(step.get('duration_minutes'))} min @ {speed} km/h{suffix}"
        )
    if session_type == "recovery":
        return _render_recovery(step, speed)
    if session_type == "long_run":
        suffix = f" (range {speed_range})" if speed_range else ""
        return f"Long run: {clean_number(step.get('distance_km'))} km @ {speed} km/h{suffix}"
    return None


def render_treadmill_instruction(details: Mapping[str, Any]) -> str | None:
    """Render current treadmill session variants, including malformed fallbacks."""

    session_type = str(details.get("session_type") or "").strip().lower()
    steps = details.get("steps")
    if not isinstance(steps, list) or not steps:
        return None
    if session_type == "intervals":
        return _render_intervals(steps)
    return _render_non_interval(session_type, steps)


def _stretch_style(step: Mapping[str, Any]) -> str:
    if step.get("is_isometric"):
        return "isometric"
    if step.get("includes_isometric_hold"):
        hold_seconds = step.get("hold_seconds")
        if hold_seconds is None:
            return "dynamic + holds"
        return f"dynamic + {hold_seconds}s hold"
    return "dynamic"


def _render_stretch_steps(steps: list[Any]) -> tuple[str, ...]:
    rendered: list[str] = []
    for raw_step in steps:
        if not isinstance(raw_step, Mapping):
            continue
        name = str(raw_step.get("name") or "").strip()
        if name:
            rendered.append(f"{name} [{_stretch_style(raw_step)}]")
    return tuple(rendered)


def render_stretch_instruction(
    details: Mapping[str, Any],
    *,
    stretch_session_type: str,
) -> str | None:
    """Render the configured stretch session without interpreting other types."""

    session_type = str(details.get("session_type") or "").strip().lower()
    if session_type != stretch_session_type:
        return None
    steps = details.get("steps")
    if not isinstance(steps, list) or not steps:
        return None

    display_name = str(details.get("display_name") or "Stretch routine").strip()
    rendered_steps = _render_stretch_steps(steps)
    if not rendered_steps:
        return display_name
    return f"{display_name}: {'; '.join(rendered_steps)}"


def _session_name(row: Mapping[str, Any], details_payload: Any) -> str:
    if isinstance(details_payload, Mapping):
        return str(row.get("comment") or row.get("exercise_name") or "Run")
    exercise = row.get("exercise_name") or f"Exercise {row.get('exercise_id')}"
    return str(exercise)


def _instruction_parts(
    details_payload: Any,
    *,
    stretch_session_type: str,
) -> list[str]:
    if not isinstance(details_payload, Mapping):
        return []
    parts = []
    treadmill = render_treadmill_instruction(details_payload)
    if treadmill:
        parts.append(treadmill)
    stretch = render_stretch_instruction(
        details_payload,
        stretch_session_type=stretch_session_type,
    )
    if stretch:
        parts.append(stretch)
    return parts


def _detail_parts(
    row: Mapping[str, Any],
    details_payload: Any,
    *,
    stretch_session_type: str,
) -> tuple[str, ...]:
    parts = _instruction_parts(
        details_payload,
        stretch_session_type=stretch_session_type,
    )
    sets = row.get("sets")
    reps = row.get("reps")
    if sets is not None and reps is not None and not parts:
        parts.append(f"{clean_number(sets)} x {clean_number(reps)}")

    weight = row.get("target_weight_kg") or row.get("weight_kg")
    if weight is not None and not details_payload:
        parts.append(f"{clean_number(weight)} kg")
    rir = row.get("rir")
    if rir is not None and not details_payload:
        parts.append(f"RIR {clean_number(rir)}")
    if row.get("optional"):
        parts.append("optional")
    return tuple(parts)


def _day_number(row: Mapping[str, Any]) -> int | None:
    day_value: Any = row.get("day_of_week")
    try:
        day_number = int(day_value)
    except (TypeError, ValueError):
        return None
    return day_number if day_number in DAY_NAMES else None


def normalize_weekly_plan_row(
    row: Mapping[str, Any],
    *,
    source_position: int,
    workout_display_order: WorkoutDisplayOrder,
    stretch_session_type: str,
) -> WeeklyPlanSession | None:
    """Normalize one heterogeneous raw plan row into an immutable session."""

    day_number = _day_number(row)
    if day_number is None:
        return None
    details_payload = row.get("details")
    details = details_payload if isinstance(details_payload, Mapping) else None
    order = workout_display_order(
        is_cardio=bool(row.get("is_cardio")),
        exercise_id=row.get("exercise_id"),
        workout_type=row.get("type"),
        details=details,
    )
    return WeeklyPlanSession(
        day_number=day_number,
        name=_session_name(row, details_payload),
        details=_detail_parts(
            row,
            details_payload,
            stretch_session_type=stretch_session_type,
        ),
        display_order=order,
        source_position=source_position,
    )


def order_weekly_plan_sessions(
    sessions: Iterable[WeeklyPlanSession],
) -> WeeklyPlanPresentation:
    """Group normalized sessions by day and apply stable schedule ordering."""

    by_day: dict[int, list[WeeklyPlanSession]] = {day: [] for day in DAY_NAMES}
    for session in sessions:
        by_day[session.day_number].append(session)
    days = tuple(
        WeeklyPlanDay(
            day_number=day_number,
            name=DAY_NAMES[day_number],
            sessions=tuple(
                sorted(
                    by_day[day_number],
                    key=lambda session: (
                        session.display_order,
                        session.source_position,
                    ),
                )
            ),
        )
        for day_number in DAY_NAMES
    )
    return WeeklyPlanPresentation(days=days)


def build_weekly_plan_presentation(
    rows: Iterable[Mapping[str, Any]],
    *,
    workout_display_order: WorkoutDisplayOrder,
    stretch_session_type: str,
) -> WeeklyPlanPresentation:
    """Normalize raw rows and return the complete ordered presentation model."""

    sessions = (
        session
        for position, row in enumerate(rows)
        if (
            session := normalize_weekly_plan_row(
                row,
                source_position=position,
                workout_display_order=workout_display_order,
                stretch_session_type=stretch_session_type,
            )
        )
        is not None
    )
    return order_weekly_plan_sessions(sessions)


def render_session_text(session: WeeklyPlanSession) -> str:
    """Render one typed session without introducing day-level delimiters."""

    if not session.details:
        return session.name
    return f"{session.name} ({' · '.join(session.details)})"


def _compatibility_session_lines(session: WeeklyPlanSession) -> tuple[str, ...]:
    """Pin the legacy rule where pipes inside session text create output lines."""

    return tuple(
        chunk.strip()
        for chunk in render_session_text(session).split("|")
        if chunk.strip()
    )


def render_weekly_plan_summary(
    presentation: WeeklyPlanPresentation,
    *,
    week_number: int,
) -> str:
    """Render the public non-empty weekly summary from typed days and sessions."""

    lines = [f"Cycle week: {week_number}"]
    for day in presentation.days:
        session_lines = tuple(
            line
            for session in day.sessions
            for line in _compatibility_session_lines(session)
        )
        if not session_lines:
            continue
        lines.append(f"{day.name}:")
        lines.extend(session_lines)
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def render_compatibility_workout_lines(
    presentation: WeeklyPlanPresentation,
) -> tuple[list[str], list[str]]:
    """Retain the private bullet/rest helper contract for existing callers."""

    bullet_lines = [
        f"- {day.name}: "
        + " | ".join(render_session_text(session) for session in day.sessions)
        for day in presentation.days
        if day.sessions
    ]
    return bullet_lines, list(presentation.rest_day_names)
