"""Running planning utilities.

This module isolates running session construction from the strength plan builder
so it can evolve toward adaptive, goal-driven planning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Sequence

from pete_e.domain import schedule_rules
from pete_e.domain.validation import BackoffRecommendation, assess_recovery_and_backoff


@dataclass(frozen=True)
class RunningGoal:
    """Optional race goal inputs for future adaptive running logic."""

    target_race: str | None = None
    race_date: date | None = None
    target_time: str | None = None
    weight_loss_target_kg: float | None = None


@dataclass(frozen=True)
class RunningLoadSummary:
    """Recent run-specific training load derived from Apple workout rows."""

    runs_28d: int = 0
    runs_90d: int = 0
    avg_weekly_km_28d: float = 0.0
    avg_weekly_km_90d: float = 0.0
    longest_run_km_90d: float = 0.0
    last_7d_km: float = 0.0
    prior_21d_weekly_km: float = 0.0
    days_since_last_run: int | None = None


@dataclass(frozen=True)
class RunningPlanProfile:
    """Plan shape chosen from running load, goal timing, and recovery metrics."""

    phase: str
    sessions_per_week: int
    include_quality: bool
    long_run_start_km: int
    long_run_increment_km: int
    easy_speed_kph: float
    long_run_speed_kph: float
    recovery_severity: str = "none"
    recovery_reasons: tuple[str, ...] = ()
    load: RunningLoadSummary = field(default_factory=RunningLoadSummary)


@dataclass(frozen=True)
class MorningRunAdjustment:
    """Run-specific advice appended to the morning report when backing off."""

    should_backoff: bool
    severity: str
    message: str
    reasons: tuple[str, ...] = ()


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None
    """Perform coerce date."""


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
    """Perform coerce float."""


def _normalise_runs(recent_runs: Iterable[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    normalised: List[Dict[str, Any]] = []
    for row in recent_runs or []:
        if not isinstance(row, dict):
            continue
        run_date = _coerce_date(row.get("workout_date") or row.get("start_time") or row.get("date"))
        distance = _coerce_float(row.get("total_distance_km") or row.get("distance_km"))
        if run_date is None or distance is None or distance <= 0:
            continue
        normalised.append(
            {
                "date": run_date,
                "distance_km": distance,
                "duration_sec": _coerce_float(row.get("duration_sec")),
                "avg_hr": _coerce_float(row.get("avg_hr")),
            }
        )
    normalised.sort(key=lambda item: item["date"])
    return normalised
    """Perform normalise runs."""


def summarise_running_load(
    recent_runs: Iterable[Dict[str, Any]] | None,
    *,
    as_of: date,
) -> RunningLoadSummary:
    """Summarise recent running volume without counting walking distance."""

    runs = _normalise_runs(recent_runs)
    if not runs:
        return RunningLoadSummary()

    start_28 = as_of - timedelta(days=27)
    start_90 = as_of - timedelta(days=89)
    start_7 = as_of - timedelta(days=6)
    prior_21_start = as_of - timedelta(days=27)
    prior_21_end = as_of - timedelta(days=7)

    runs_28 = [run for run in runs if start_28 <= run["date"] <= as_of]
    runs_90 = [run for run in runs if start_90 <= run["date"] <= as_of]
    runs_7 = [run for run in runs if start_7 <= run["date"] <= as_of]
    prior_21 = [run for run in runs if prior_21_start <= run["date"] <= prior_21_end]

    total_28 = sum(run["distance_km"] for run in runs_28)
    total_90 = sum(run["distance_km"] for run in runs_90)
    last_7 = sum(run["distance_km"] for run in runs_7)
    prior_21_total = sum(run["distance_km"] for run in prior_21)
    last_run_date = max(run["date"] for run in runs)

    return RunningLoadSummary(
        runs_28d=len(runs_28),
        runs_90d=len(runs_90),
        avg_weekly_km_28d=total_28 / 4.0,
        avg_weekly_km_90d=total_90 / (90.0 / 7.0),
        longest_run_km_90d=max((run["distance_km"] for run in runs_90), default=0.0),
        last_7d_km=last_7,
        prior_21d_weekly_km=prior_21_total / 3.0,
        days_since_last_run=(as_of - last_run_date).days,
    )


def _assess_recovery(
    health_metrics: Sequence[Dict[str, Any]] | None,
    *,
    action_date: date,
) -> BackoffRecommendation | None:
    rows = list(health_metrics or [])
    if not rows:
        return None
    try:
        return assess_recovery_and_backoff(rows, action_date)
    except Exception:
        return None
    """Perform assess recovery."""


def _phase_for_load(load: RunningLoadSummary, goal: RunningGoal | None, as_of: date) -> str:
    foundation = (
        load.runs_28d < 8
        or load.avg_weekly_km_28d < 15.0
        or load.longest_run_km_90d < 8.0
    )
    if foundation:
        return "foundation"

    base = load.avg_weekly_km_28d < 30.0 or load.longest_run_km_90d < 14.0
    if base:
        return "base"

    if goal and goal.race_date:
        weeks_to_race = (goal.race_date - as_of).days / 7.0
        if weeks_to_race <= 18:
            return "marathon_specific"
    return "aerobic_build"
    """Perform phase for load."""


def _long_run_start_for_phase(load: RunningLoadSummary, phase: str) -> int:
    longest = load.longest_run_km_90d
    if longest <= 0:
        return 4
    if phase == "foundation":
        return max(4, min(6, round(longest + 0.5)))
    if phase == "base":
        return max(7, min(12, round(longest + 1.0)))
    return max(10, min(18, round(longest + 2.0)))
    """Perform long run start for phase."""


def build_running_plan_profile(
    *,
    plan_start_date: date,
    goal: RunningGoal | None = None,
    health_metrics: Sequence[Dict[str, Any]] | None = None,
    recent_runs: Iterable[Dict[str, Any]] | None = None,
) -> RunningPlanProfile:
    """Choose a conservative running block from current durability and recovery."""

    as_of = plan_start_date - timedelta(days=1)
    load = summarise_running_load(recent_runs, as_of=as_of)
    recovery = _assess_recovery(health_metrics, action_date=plan_start_date)
    recovery_severity = recovery.severity if recovery else "none"
    recovery_reasons = tuple(recovery.reasons) if recovery else ()
    phase = _phase_for_load(load, goal, as_of)

    if recovery_severity == "severe":
        return RunningPlanProfile(
            phase="recovery",
            sessions_per_week=1,
            include_quality=False,
            long_run_start_km=max(3, min(5, _long_run_start_for_phase(load, "foundation"))),
            long_run_increment_km=0,
            easy_speed_kph=7.5,
            long_run_speed_kph=7.5,
            recovery_severity=recovery_severity,
            recovery_reasons=recovery_reasons,
            load=load,
        )

    if recovery_severity == "moderate":
        return RunningPlanProfile(
            phase="recovery",
            sessions_per_week=2,
            include_quality=False,
            long_run_start_km=max(4, min(6, _long_run_start_for_phase(load, "foundation"))),
            long_run_increment_km=0,
            easy_speed_kph=7.8,
            long_run_speed_kph=7.8,
            recovery_severity=recovery_severity,
            recovery_reasons=recovery_reasons,
            load=load,
        )

    high_weight_loss = bool(goal and (goal.weight_loss_target_kg or 0) >= 10)
    if phase == "foundation":
        sessions = 3
        easy_speed = 8.2 if high_weight_loss else 8.4
        long_speed = 8.0 if high_weight_loss else 8.2
        include_quality = False
    elif phase == "base":
        sessions = 4
        easy_speed = 8.5
        long_speed = 8.3
        include_quality = False
    else:
        sessions = 4 if high_weight_loss else 5
        easy_speed = 8.8
        long_speed = 8.6
        include_quality = recovery_severity == "none"

    if recovery_severity == "mild":
        include_quality = False
        sessions = min(sessions, 3)

    return RunningPlanProfile(
        phase=phase,
        sessions_per_week=sessions,
        include_quality=include_quality,
        long_run_start_km=_long_run_start_for_phase(load, phase),
        long_run_increment_km=1,
        easy_speed_kph=easy_speed,
        long_run_speed_kph=long_speed,
        recovery_severity=recovery_severity,
        recovery_reasons=recovery_reasons,
        load=load,
    )


def _run_payload(
    *,
    day_of_week: int,
    comment: str,
    details: Dict[str, Any],
    optional: bool = False,
    recovery_focused: bool = False,
) -> Dict[str, Any]:
    return {
        "day_of_week": day_of_week,
        "exercise_id": schedule_rules.RUN_CARDIO_EXERCISE_ID,
        "sets": 1,
        "reps": 1,
        "slot": "conditioning",
        "is_cardio": True,
        "comment": comment,
        "details": details,
        "optional": optional,
        "recovery_focused": recovery_focused,
    }
    """Perform run payload."""


def _progressed_long_run_distance(profile: RunningPlanProfile, week_number: int) -> int:
    start = profile.long_run_start_km
    if profile.long_run_increment_km <= 0:
        return start
    if week_number % 4 == 0:
        return max(start, start + max(0, week_number - 3))
    return start + ((week_number - 1) * profile.long_run_increment_km)
    """Perform progressed long run distance."""


def _daily_load_backoff(load: RunningLoadSummary) -> tuple[str, tuple[str, ...]] | None:
    if load.prior_21d_weekly_km <= 0:
        return None
    jump_ratio = load.last_7d_km / load.prior_21d_weekly_km
    if load.last_7d_km >= 8.0 and jump_ratio >= 1.50:
        return (
            "mild",
            (
                f"run load jumped to {load.last_7d_km:.1f} km in 7 days "
                f"vs {load.prior_21d_weekly_km:.1f} km/week baseline",
            ),
        )
    return None
    """Perform daily load backoff."""


def assess_morning_run_adjustment(
    *,
    health_metrics: Sequence[Dict[str, Any]] | None,
    recent_runs: Iterable[Dict[str, Any]] | None,
    action_date: date,
    planned_session_names: Sequence[str] | None = None,
) -> MorningRunAdjustment | None:
    """Return a run back-off instruction for the morning message, if needed."""

    recovery = _assess_recovery(health_metrics, action_date=action_date)
    load = summarise_running_load(recent_runs, as_of=action_date - timedelta(days=1))
    load_backoff = _daily_load_backoff(load)

    severity = recovery.severity if recovery else "none"
    reasons: List[str] = list(recovery.reasons if recovery else [])
    if load_backoff:
        load_severity, load_reasons = load_backoff
        reasons.extend(load_reasons)
        if severity == "none":
            severity = load_severity

    if severity == "none":
        return None

    planned_names = [str(name).strip() for name in planned_session_names or [] if str(name).strip()]
    planned_text = ", ".join(planned_names[:2])
    planned_lower = " ".join(name.lower() for name in planned_names)
    has_quality = any(token in planned_lower for token in ("quality", "tempo", "interval", "steady", "long run"))

    if severity == "severe":
        instruction = "skip today's run; use rest, mobility, or an easy walk only"
    elif severity == "moderate":
        instruction = "replace running with rest or 20-30 minutes very easy walking"
    elif has_quality:
        instruction = "swap today's run for 20-30 minutes easy, conversational effort"
    else:
        instruction = "keep any run short and easy; cap it before fatigue changes your stride"

    if planned_text:
        message = f"Run adjustment for {planned_text}: {instruction}."
    else:
        message = f"Run adjustment: {instruction}."

    if reasons:
        message += " Trigger: " + "; ".join(reasons[:2]) + "."

    return MorningRunAdjustment(
        should_backoff=True,
        severity=severity,
        message=message,
        reasons=tuple(reasons),
    )


class RunningPlanner:
    """Builds running sessions for each training week."""

    def build_week_sessions(
        self,
        *,
        week_number: int,
        goal: RunningGoal | None = None,
        health_metrics: Sequence[Dict[str, Any]] | None = None,
        recent_runs: Iterable[Dict[str, Any]] | None = None,
        plan_start_date: date | None = None,
    ) -> List[Dict[str, Any]]:
        """Return running workouts for a given week.

        ``goal`` and ``health_metrics`` are accepted now so the calling code can
        pass richer context as the adaptive planning rules are expanded.
        """

        profile = build_running_plan_profile(
            plan_start_date=plan_start_date or date.today(),
            goal=goal,
            health_metrics=health_metrics,
            recent_runs=recent_runs,
        )

        if profile.sessions_per_week <= 1:
            return [
                _run_payload(
                    day_of_week=3,
                    comment="Recovery run-walk",
                    details=schedule_rules.recovery_micro_run_details(
                        duration_minutes=20,
                        speed_kph=profile.easy_speed_kph,
                    ),
                    optional=True,
                    recovery_focused=True,
                )
            ]

        sessions: List[Dict[str, Any]] = [
            _run_payload(
                day_of_week=1,
                comment="Easy run",
                details=schedule_rules.easy_run_details(
                    duration_minutes=20 if profile.phase == "foundation" else 25,
                    speed_kph=profile.easy_speed_kph,
                    min_speed_kph=profile.easy_speed_kph - 0.2,
                    max_speed_kph=profile.easy_speed_kph + 0.2,
                ),
                recovery_focused=True,
            )
        ]

        if profile.sessions_per_week >= 4:
            sessions.append(
                _run_payload(
                    day_of_week=3,
                    comment="Aerobic support run",
                    details=schedule_rules.easy_run_details(
                        duration_minutes=20,
                        speed_kph=profile.easy_speed_kph,
                        min_speed_kph=profile.easy_speed_kph - 0.2,
                        max_speed_kph=profile.easy_speed_kph + 0.2,
                    ),
                    optional=True,
                    recovery_focused=True,
                )
            )

        if profile.include_quality:
            quality_details = (
                schedule_rules.quality_intervals_details()
                if week_number % 2 == 1
                else schedule_rules.quality_tempo_details()
            )
            sessions.append(
                _run_payload(
                    day_of_week=4,
                    comment="Quality run",
                    details=quality_details,
                )
            )
        else:
            sessions.append(
                _run_payload(
                    day_of_week=4,
                    comment="Easy aerobic run",
                    details=schedule_rules.easy_run_details(
                        duration_minutes=25 if profile.phase == "foundation" else 30,
                        speed_kph=profile.easy_speed_kph,
                        min_speed_kph=profile.easy_speed_kph - 0.2,
                        max_speed_kph=profile.easy_speed_kph + 0.2,
                    ),
                    recovery_focused=True,
                )
            )

        if profile.sessions_per_week >= 5:
            sessions.append(
                _run_payload(
                    day_of_week=5,
                    comment="Recovery micro run",
                    details=schedule_rules.recovery_micro_run_details(
                        duration_minutes=12,
                        speed_kph=max(7.8, profile.easy_speed_kph - 0.3),
                    ),
                    optional=True,
                    recovery_focused=True,
                )
            )

        if profile.sessions_per_week >= 2:
            long_run_distance = _progressed_long_run_distance(profile, week_number)
            sessions.append(
                _run_payload(
                    day_of_week=6,
                    comment="Long run",
                    details=schedule_rules.long_run_details(
                        distance_km=long_run_distance,
                        speed_kph=profile.long_run_speed_kph,
                        min_speed_kph=profile.long_run_speed_kph - 0.2,
                        max_speed_kph=profile.long_run_speed_kph + 0.2,
                    ),
                )
            )

        return sorted(sessions, key=lambda item: (item["day_of_week"], item["comment"]))
