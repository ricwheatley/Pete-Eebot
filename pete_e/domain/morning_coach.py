"""Session-aware coaching decisions for the morning report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence

from pete_e.domain import schedule_rules
from pete_e.domain.running_planner import summarise_running_load
from pete_e.domain.validation import (
    BackoffRecommendation,
    ReadinessSummary,
    ValidationDecision,
    assess_recovery_and_backoff,
)
from pete_e.utils import converters


_SEVERITY_RANK = {"none": 0, "mild": 1, "moderate": 2, "severe": 3}
_WEIGHT_MULTIPLIER_BY_SEVERITY = {
    "mild": 0.95,
    "moderate": 0.90,
    "severe": 0.85,
}


@dataclass(frozen=True)
class DailyWgerAdjustment:
    """A scoped payload adjustment for today's exported wger session."""

    day_of_week: int
    severity: str
    weight_multiplier: float
    set_multiplier: float
    rir_increment: int
    reasons: tuple[str, ...] = ()
    adjust_strength: bool = False
    adjust_runs: bool = False


@dataclass(frozen=True)
class MorningTrainingAdjustment:
    """Coaching text plus optional wger update instructions."""

    message: str | None
    should_adjust: bool
    severity: str
    reasons: tuple[str, ...] = ()
    wger_adjustment: DailyWgerAdjustment | None = None
    validation_decision: ValidationDecision | None = None


@dataclass(frozen=True)
class _PlanItem:
    name: str
    day_of_week: int
    exercise_id: int | None = None
    is_cardio: bool = False
    sets: int | None = None
    reps: int | None = None
    rir: float | None = None
    target_weight_kg: float | None = None
    details: Mapping[str, Any] | None = None


def build_morning_training_adjustment(
    *,
    health_metrics: Sequence[dict[str, Any]] | None,
    recent_runs: Iterable[dict[str, Any]] | None,
    action_date: date,
    plan_rows: Iterable[Mapping[str, Any]] | None,
) -> MorningTrainingAdjustment | None:
    """Return session-specific morning coaching and any wger payload adjustment."""

    items = _normalise_plan_items(plan_rows, default_day=action_date.isoweekday())
    recovery = _assess_recovery(health_metrics, action_date=action_date)
    recovery_severity = _normalise_severity(recovery.severity if recovery else "none")
    reasons: list[str] = list(recovery.reasons if recovery and recovery.needs_backoff else [])

    run_load_backoff = _assess_run_load(recent_runs, action_date=action_date)
    run_load_severity = "none"
    if run_load_backoff is not None:
        run_load_severity, run_load_reasons = run_load_backoff
        reasons.extend(run_load_reasons)

    runs = [item for item in items if _is_run(item)]
    strength = [item for item in items if _is_strength(item)]
    has_plan = bool(items)

    adjust_strength = bool(strength and recovery and recovery.needs_backoff)
    adjust_runs = bool(runs and (recovery_severity != "none" or run_load_backoff is not None))
    severity = _max_severity(recovery_severity, run_load_severity)

    if not adjust_strength and not adjust_runs:
        if not has_plan:
            return None
        return MorningTrainingAdjustment(
            message=_build_steady_session_message(items, strength=strength, runs=runs),
            should_adjust=False,
            severity="none",
        )

    set_multiplier = float(recovery.set_multiplier if recovery else 1.0)
    rir_increment = int(recovery.rir_increment if recovery else 0)
    weight_multiplier = _WEIGHT_MULTIPLIER_BY_SEVERITY.get(severity, 1.0)
    wger_adjustment = DailyWgerAdjustment(
        day_of_week=action_date.isoweekday(),
        severity=severity,
        weight_multiplier=weight_multiplier,
        set_multiplier=set_multiplier,
        rir_increment=rir_increment,
        reasons=tuple(reasons),
        adjust_strength=adjust_strength,
        adjust_runs=adjust_runs,
    )

    validation_decision = _validation_decision_from_adjustment(
        wger_adjustment,
        recovery=recovery,
    )
    return MorningTrainingAdjustment(
        message=_build_backoff_message(
            items,
            strength=strength,
            runs=runs,
            adjustment=wger_adjustment,
        ),
        should_adjust=True,
        severity=severity,
        reasons=tuple(reasons),
        wger_adjustment=wger_adjustment,
        validation_decision=validation_decision,
    )


def _normalise_plan_items(
    rows: Iterable[Mapping[str, Any]] | None,
    *,
    default_day: int,
) -> list[_PlanItem]:
    items: list[_PlanItem] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        details = row.get("details")
        details_map = details if isinstance(details, Mapping) else None
        display_name = (
            _clean_text(details_map.get("display_name") if details_map else None)
            or _clean_text(row.get("exercise_name"))
            or _clean_text(row.get("comment"))
            or "Planned session"
        )
        exercise_id = _to_int(row.get("exercise_id") or row.get("exercise"))
        items.append(
            _PlanItem(
                name=display_name,
                day_of_week=_to_int(row.get("day_of_week")) or default_day,
                exercise_id=exercise_id,
                is_cardio=bool(row.get("is_cardio")),
                sets=_to_int(row.get("sets")),
                reps=_to_int(row.get("reps")),
                rir=converters.to_float(row.get("rir")),
                target_weight_kg=converters.to_float(row.get("target_weight_kg")),
                details=details_map,
            )
        )
    return items


def _assess_recovery(
    health_metrics: Sequence[dict[str, Any]] | None,
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


def _assess_run_load(
    recent_runs: Iterable[dict[str, Any]] | None,
    *,
    action_date: date,
) -> tuple[str, tuple[str, ...]] | None:
    load = summarise_running_load(recent_runs, as_of=action_date - timedelta(days=1))
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


def _build_steady_session_message(
    items: Sequence[_PlanItem],
    *,
    strength: Sequence[_PlanItem],
    runs: Sequence[_PlanItem],
) -> str:
    session = _session_summary(items)
    if strength:
        target_text = _target_summary(strength)
        if target_text:
            return f"Today's gym plan: {session}. Keep the programmed loads; key targets are {target_text}."
        return f"Today's gym plan: {session}. Keep the programmed effort and stop sets before form drifts."
    if runs:
        return f"Today's run plan: {session}. Keep it controlled enough that the final third still feels tidy."
    return f"Today's plan: {session}. Keep it clean and leave a little in reserve."


def _build_backoff_message(
    items: Sequence[_PlanItem],
    *,
    strength: Sequence[_PlanItem],
    runs: Sequence[_PlanItem],
    adjustment: DailyWgerAdjustment,
) -> str:
    parts: list[str] = []

    if strength and adjustment.adjust_strength:
        effort = _effort_adjustment_text(adjustment)
        readiness = _readiness_reason_sentence(adjustment.reasons)
        session_name = _session_summary(strength)
        if readiness:
            parts.append(
                f"{readiness} so we're going to adjust today's {session_name} session. We'll {effort}"
            )
        else:
            parts.append(
                f"We're going to adjust today's {session_name} session. We'll {effort}"
            )

    if runs and adjustment.adjust_runs:
        run_names = _session_summary(runs)
        if adjustment.severity == "severe":
            instruction = "skip intensity; use rest, mobility, or an easy walk"
        elif adjustment.severity == "moderate":
            instruction = "replace the session with 20-30 minutes very easy"
        else:
            instruction = "keep it easy and cap it before fatigue changes your stride"
        parts.append(f"Today's run adjustment for {run_names}: {instruction}")

    if not parts:
        parts.append(
            "Readiness adjustment: no programmed session today, so keep it to easy walking or mobility"
        )

    return ". ".join(part.rstrip(".") for part in parts) + "."


def _validation_decision_from_adjustment(
    adjustment: DailyWgerAdjustment,
    *,
    recovery: BackoffRecommendation | None,
) -> ValidationDecision:
    recommendation = BackoffRecommendation(
        needs_backoff=True,
        severity=adjustment.severity,
        reasons=list(adjustment.reasons),
        set_multiplier=adjustment.set_multiplier,
        rir_increment=adjustment.rir_increment,
        metrics=dict(recovery.metrics if recovery else {}),
    )
    readiness = ReadinessSummary(
        state="backoff",
        headline=f"{adjustment.severity.title()} readiness back-off",
        tip="Use the adjusted prescription for today's session.",
        severity=adjustment.severity,
        breach_ratio=float((recovery.metrics or {}).get("severity_ratio", 0.0)) if recovery else 0.0,
        reasons=list(adjustment.reasons),
    )
    return ValidationDecision(
        needs_backoff=True,
        should_apply=False,
        explanation=(
            f"Daily morning adjustment, severity={adjustment.severity}; "
            "scoped to today's Wger export."
        ),
        log_entries=[
            f"severity={adjustment.severity}",
            f"weight_multiplier={adjustment.weight_multiplier:.2f}",
            f"set_multiplier={adjustment.set_multiplier:.2f}",
            f"rir_increment={adjustment.rir_increment}",
            *adjustment.reasons,
        ],
        readiness=readiness,
        recommendation=recommendation,
        applied=False,
    )


def _is_run(item: _PlanItem) -> bool:
    session_type = _session_type(item)
    if session_type in schedule_rules.RUN_SESSION_TYPES:
        return True
    if item.exercise_id in {schedule_rules.TREADMILL_RUN_ID, schedule_rules.OUTDOOR_RUN_ID}:
        return True
    lowered = item.name.lower()
    return any(token in lowered for token in ("run", "jog", "interval", "tempo", "fartlek"))


def _is_strength(item: _PlanItem) -> bool:
    if _is_run(item):
        return False
    if item.is_cardio:
        return False
    if _session_type(item) == schedule_rules.STRETCH_SESSION_TYPE:
        return False
    return item.sets is not None or item.reps is not None or item.target_weight_kg is not None


def _session_type(item: _PlanItem) -> str:
    details = item.details if isinstance(item.details, Mapping) else {}
    return str(details.get("session_type") or "").strip().lower()


def _session_summary(items: Sequence[_PlanItem]) -> str:
    names: list[str] = []
    for item in items:
        if item.name not in names:
            names.append(item.name)
        if len(names) == 3:
            break
    if not names:
        return "Rest"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    return f"{names[0]}, {names[1]} + more"


def _target_summary(items: Sequence[_PlanItem]) -> str | None:
    targets = [
        f"{item.name} {_format_weight(item.target_weight_kg)}"
        for item in items
        if item.target_weight_kg is not None
    ]
    return "; ".join(targets[:3]) or None


def _load_change_summary(items: Sequence[_PlanItem], multiplier: float) -> str | None:
    changes: list[str] = []
    for item in items:
        before = item.target_weight_kg
        if before is None:
            continue
        after = _round_weight(before * multiplier)
        if abs(after - before) < 0.01:
            continue
        changes.append(f"{item.name} {_format_weight(before)} -> {_format_weight(after)}")
        if len(changes) == 2:
            break
    return "; ".join(changes) or None


def _effort_adjustment_text(adjustment: DailyWgerAdjustment) -> str:
    clauses: list[str] = []
    if adjustment.set_multiplier < 0.999:
        clauses.append(f"cap sets at {int(round(adjustment.set_multiplier * 100))}%")
    if adjustment.rir_increment:
        clauses.append(f"add RIR +{adjustment.rir_increment}")
    if not clauses:
        return "keep every set comfortably submaximal"
    return ", ".join(clauses) + " and keep reps crisp"


def _readiness_reason_sentence(reasons: Sequence[str]) -> str:
    cleaned = [reason.strip().rstrip(".") for reason in reasons if reason and reason.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return f"{cleaned[0]} and {cleaned[1]}"


def _percent_drop(multiplier: float) -> str:
    return f"{max(0, int(round((1.0 - multiplier) * 100)))}%"


def _format_weight(weight_kg: float | None) -> str:
    if weight_kg is None:
        return "bodyweight"
    rounded = round(float(weight_kg), 2)
    if rounded.is_integer():
        return f"{int(rounded)} kg"
    return f"{rounded:.2f}".rstrip("0").rstrip(".") + " kg"


def _round_weight(weight_kg: float) -> float:
    return round(round(float(weight_kg) * 2) / 2, 2)


def _max_severity(left: str, right: str) -> str:
    left = _normalise_severity(left)
    right = _normalise_severity(right)
    return left if _SEVERITY_RANK[left] >= _SEVERITY_RANK[right] else right


def _normalise_severity(value: str | None) -> str:
    severity = str(value or "none").strip().lower()
    return severity if severity in _SEVERITY_RANK else "none"


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
