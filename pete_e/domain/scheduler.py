"""Session timing scheduler."""

from datetime import datetime, time
from typing import List, Dict, Any, Optional


def _normalized_type(session: Dict[str, Any]) -> str:
    raw_type = session.get("type")
    return str(raw_type).strip().lower() if isinstance(raw_type, str) else ""


def _coerce_time(value: Any) -> Optional[time]:
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return time.fromisoformat(text)
        except ValueError:
            pass
        for fmt in ("%I:%M%p", "%I:%M %p", "%H%M"):
            try:
                return datetime.strptime(text, fmt).time()
            except ValueError:
                continue
    return None


def _extract_start(session: Dict[str, Any]) -> Optional[time]:
    for key in ("start", "time", "scheduled_time"):
        start = _coerce_time(session.get(key))
        if start:
            return start
    return None


def _duration_minutes(session: Dict[str, Any]) -> Optional[int]:
    for key in ("duration_minutes", "duration"):
        value = session.get(key)
        if isinstance(value, (int, float)):
            minutes = int(round(value))
            if minutes > 0:
                return minutes
    return None


def _compute_end(start_time: time, minutes: int) -> time:
    total_minutes = start_time.hour * 60 + start_time.minute + minutes
    hour, minute = divmod(total_minutes, 60)
    return time(hour % 24, minute, start_time.second, start_time.microsecond)


def _assign_session_times(session: Dict[str, Any], start_time: Optional[time], fallback_duration: Optional[int] = None) -> None:
    if start_time is None:
        return
    session["start"] = start_time
    duration = _duration_minutes(session)
    if duration is None:
        duration = fallback_duration
    if duration is None:
        return
    session["end"] = _compute_end(start_time, duration)


def assign_times(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assign start/end times based on Blaze session position."""
    blaze_start: Optional[time] = None

    for session in sessions:
        if _normalized_type(session) == "blaze":
            candidate = _extract_start(session)
            if candidate is not None:
                blaze_start = candidate
                break

    if blaze_start is None:
        return sessions

    weights_start = time(7, 0) if blaze_start < time(7, 0) else time(6, 0)

    for session in sessions:
        session_type = _normalized_type(session)
        if session_type == "blaze":
            start_time = _extract_start(session) or blaze_start
            _assign_session_times(session, start_time, fallback_duration=45)
        elif session_type == "weights":
            _assign_session_times(session, weights_start)

    return sessions
