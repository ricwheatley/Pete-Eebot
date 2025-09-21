# pete_e/domain/validation.py
from __future__ import annotations

import copy

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from statistics import median, mean
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pete_e.config import settings
from pete_e.infrastructure import log_utils


# Windows are expressed in days to avoid calendar edge cases.
# 30, 60, 90 and 180 approximate the prior 1, 2, 3 and 6 months.
_BASELINE_WINDOWS_DAYS: List[int] = [30, 60, 90, 180]
_MIN_DAYS_PER_WINDOW: int = 14  # require at least this many points to trust a window
_LAST_N_DAYS_FOR_OBS: int = 7   # assess the most recent 7 days before the upcoming week
_HRV_METRIC_KEYS: Tuple[str, ...] = (
    "hrv_sdnn_ms",
    "hrv_rmssd_ms",
    "hrv_daily_ms",
    "heart_rate_variability",
    "hrv",
)


_EXPECTED_PLAN_WEEKS: int = 4
_EXPECTED_TRAINING_DAYS: Tuple[int, ...] = (1, 2, 4, 5)
_DAY_NAME_BY_NUMBER: Dict[int, str] = {
    1: 'Monday',
    2: 'Tuesday',
    3: 'Wednesday',
    4: 'Thursday',
    5: 'Friday',
    6: 'Saturday',
    7: 'Sunday',
}


def _format_day_list(days: Iterable[int]) -> str:
    ordered = sorted(days)
    names = [_DAY_NAME_BY_NUMBER.get(day, str(day)) for day in ordered]
    return ', '.join(names)

@dataclass(frozen=True)
class WindowStats:
    days: int
    start: date
    end: date
    values: List[float]
    median_value: float
    mean_value: float


@dataclass(frozen=True)
class BaselineResult:
    value: Optional[float]
    by_window: Dict[int, WindowStats]  # keyed by window length (days)


@dataclass(frozen=True)
class BackoffRecommendation:
    needs_backoff: bool
    severity: str  # "none", "mild", "moderate", "severe"
    reasons: List[str]
    set_multiplier: float
    rir_increment: int
    metrics: Dict[str, Any]  # observed and baseline metrics for transparency

@dataclass(frozen=True)
class ReadinessSummary:
    state: str
    headline: str
    tip: Optional[str]
    severity: str
    breach_ratio: float
    reasons: List[str]


@dataclass(frozen=True)
class ValidationDecision:
    """Outcome of plan validation ahead of Wger export or calibration."""

    needs_backoff: bool
    applied: bool
    explanation: str
    log_entries: List[str]
    readiness: ReadinessSummary
    recommendation: BackoffRecommendation


@dataclass(frozen=True)
class MuscleBalanceReport:
    balanced: bool
    totals_by_group: Dict[str, float]
    imbalance_ratio: float
    missing_groups: List[str]
    tolerance: float


def _ensure_date(value: Any) -> Optional[date]:
    '''Best effort conversion to date.'''
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _resolve_plan_context(dal: Any, week_start_date: date) -> Optional[Tuple[int, date]]:
    get_active_plan = getattr(dal, 'get_active_plan', None)
    plan: Optional[Dict[str, Any]] = None
    if callable(get_active_plan):
        try:
            plan = get_active_plan()
        except Exception:
            plan = None
    if plan:
        plan_id = plan.get('id')
        start_date = _ensure_date(plan.get('start_date'))
        if plan_id is not None and start_date is not None:
            return int(plan_id), start_date

    find_by_start = getattr(dal, 'find_plan_by_start_date', None)
    if callable(find_by_start):
        try:
            plan = find_by_start(week_start_date)
        except Exception:
            plan = None
        if plan:
            plan_id = plan.get('id')
            start_date = _ensure_date(plan.get('start_date')) or week_start_date
            if plan_id is not None and start_date is not None:
                return int(plan_id), start_date
    return None


def collect_adherence_snapshot(dal: Any, week_start_date: date) -> Optional[Dict[str, Any]]:
    '''Return planned vs actual muscle volume coverage for the prior week.'''
    context = _resolve_plan_context(dal, week_start_date)
    if not context:
        return None
    plan_id, plan_start = context

    days_since_start = (week_start_date - plan_start).days
    if days_since_start < 0:
        return None
    week_number = (days_since_start // 7) + 1
    prev_week_number = week_number - 1
    if prev_week_number <= 0:
        return None

    get_planned = getattr(dal, 'get_plan_muscle_volume', None)
    get_actual = getattr(dal, 'get_actual_muscle_volume', None)
    if not callable(get_planned) or not callable(get_actual):
        return None

    try:
        planned_rows = get_planned(plan_id, prev_week_number) or []
    except Exception:
        return None

    if not planned_rows:
        return None

    prev_week_start = week_start_date - timedelta(days=7)
    prev_week_end = week_start_date - timedelta(days=1)

    try:
        actual_rows = get_actual(prev_week_start, prev_week_end) or []
    except Exception:
        actual_rows = []

    planned_by_muscle: Dict[int, float] = {}
    for row in planned_rows:
        muscle_id = row.get('muscle_id')
        if muscle_id is None:
            continue
        try:
            planned_val = float(row.get('target_volume_kg', 0.0))
        except (TypeError, ValueError):
            continue
        if planned_val <= 0:
            continue
        planned_by_muscle[int(muscle_id)] = planned_val

    if not planned_by_muscle:
        return None

    actual_by_muscle: Dict[int, float] = {}
    for row in actual_rows:
        muscle_id = row.get('muscle_id')
        if muscle_id is None:
            continue
        try:
            actual_val = float(row.get('actual_volume_kg', 0.0))
        except (TypeError, ValueError):
            continue
        key = int(muscle_id)
        actual_by_muscle[key] = actual_by_muscle.get(key, 0.0) + actual_val

    total_planned = sum(planned_by_muscle.values())
    total_actual = sum(actual_by_muscle.get(mid, 0.0) for mid in planned_by_muscle.keys())
    ratio = (total_actual / total_planned) if total_planned > 0 else 0.0

    muscles: List[Dict[str, float]] = []
    for mid in sorted(planned_by_muscle.keys()):
        planned_val = planned_by_muscle[mid]
        actual_val = actual_by_muscle.get(mid, 0.0)
        muscle_ratio = (actual_val / planned_val) if planned_val > 0 else 0.0
        muscles.append(
            {
                'muscle_id': mid,
                'planned': planned_val,
                'actual': actual_val,
                'ratio': muscle_ratio,
            }
        )

    low_muscles = [m for m in muscles if m['planned'] > 0 and m['ratio'] < 0.70]
    high_muscles = [m for m in muscles if m['planned'] > 0 and m['ratio'] > 1.10]

    return {
        'plan_id': plan_id,
        'week_number': prev_week_number,
        'week_start': prev_week_start,
        'week_end': prev_week_end,
        'planned_total': total_planned,
        'actual_total': total_actual,
        'ratio': ratio,
        'muscles': muscles,
        'low_muscles': low_muscles,
        'high_muscles': high_muscles,
        'available': True,
    }


def _evaluate_adherence_adjustment(
    dal: Any,
    week_start_date: date,
    recovery: BackoffRecommendation,
) -> Dict[str, Any]:
    base_result: Dict[str, Any] = {
        'direction': 'maintain',
        'set_multiplier': 1.0,
        'rir_adjust': 0,
        'reasons': [],
        'log_entries': [],
        'metrics': {'available': False},
    }
    snapshot = collect_adherence_snapshot(dal, week_start_date)
    if not snapshot:
        return base_result

    ratio = snapshot.get('ratio', 0.0) or 0.0
    low_muscles = snapshot.get('low_muscles', [])
    high_muscles = snapshot.get('high_muscles', [])

    reasons = [
        (
            f"Adherence ratio {ratio:.2f} (actual {snapshot.get('actual_total', 0.0):.1f}kg"
            f" vs planned {snapshot.get('planned_total', 0.0):.1f}kg)"
        )
    ]
    log_entries = [
        f'adherence_ratio={ratio:.2f}',
        f'adherence_low_groups={len(low_muscles)}',
        f'adherence_high_groups={len(high_muscles)}',
    ]

    direction = 'maintain'
    multiplier = 1.0
    rir_adjust = 0
    gated = False

    if ratio < 0.70 or len(low_muscles) >= 2:
        direction = 'reduce'
        multiplier = 0.90
        if low_muscles:
            low_desc = ', '.join(f"{m['muscle_id']}({m['ratio']:.2f})" for m in low_muscles[:4])
            reasons.append(f'Low adherence muscles: {low_desc}')
        log_entries.append('adherence_direction=reduce')
    elif ratio > 1.10:
        log_entries.append('adherence_requested=increase')
        if recovery.needs_backoff:
            gated = True
            reasons.append(f'Increase gated by recovery severity={recovery.severity}')
            log_entries.append('adherence_applied=maintain')
            log_entries.append('adherence_gated_by=recovery')
        else:
            direction = 'increase'
            multiplier = 1.05
            if high_muscles:
                high_desc = ', '.join(f"{m['muscle_id']}({m['ratio']:.2f})" for m in high_muscles[:4])
                reasons.append(f'High adherence muscles: {high_desc}')
            log_entries.append('adherence_direction=increase')
    else:
        log_entries.append('adherence_direction=maintain')

    metrics = dict(snapshot)
    metrics.update(
        {
            'requested_direction': (
                'increase' if ratio > 1.10 else 'reduce' if ratio < 0.70 or len(low_muscles) >= 2 else 'maintain'
            ),
            'applied_direction': direction,
            'multiplier': multiplier,
            'rir_adjust': rir_adjust,
            'gated_by_recovery': gated,
        }
    )

    base_result.update(
        {
            'direction': direction,
            'set_multiplier': multiplier,
            'rir_adjust': rir_adjust,
            'reasons': reasons,
            'log_entries': log_entries,
            'metrics': metrics,
        }
    )
    return base_result

def ensure_muscle_balance(
    plan: Dict[str, Any],
    tolerance: float = 0.25,
    required_groups: Optional[Iterable[str]] = None,
) -> MuscleBalanceReport:
    if tolerance < 0:
        raise ValueError('tolerance must be non-negative')
    groups = tuple(required_groups) if required_groups is not None else ('upper_push', 'upper_pull', 'lower')
    totals: Dict[str, float] = {}
    for week in plan.get('weeks', []):
        workouts = week.get('workouts', [])
        for workout in workouts:
            if not isinstance(workout, dict):
                continue
            group = workout.get('muscle_group')
            sets_value = workout.get('sets')
            if group is None:
                continue
            try:
                sets_float = float(sets_value)
            except (TypeError, ValueError):
                continue
            totals[group] = totals.get(group, 0.0) + sets_float

    for group in groups:
        totals.setdefault(group, 0.0)

    missing = [group for group in groups if totals[group] <= 0]

    active = [totals[group] for group in groups if totals[group] > 0]
    if len(active) < len(groups):
        imbalance_ratio = float('inf')
    else:
        min_volume = min(active)
        max_volume = max(active)
        imbalance_ratio = max_volume / min_volume if min_volume > 0 else float('inf')

    balanced = not missing and imbalance_ratio <= (1 + tolerance)
    return MuscleBalanceReport(
        balanced=balanced,
        totals_by_group=dict(totals),
        imbalance_ratio=imbalance_ratio,
        missing_groups=missing,
        tolerance=tolerance,
    )



def validate_plan_structure(plan: Dict[str, Any], block_start_date: Optional[date] = None) -> None:
    """Validate overall plan structure before persistence or export."""

    weeks = plan.get('weeks')
    errors: List[str] = []

    if not isinstance(weeks, list) or not weeks:
        errors.append('plan must contain 4 weeks but none found')
        raise ValueError('Plan structure validation failed: ' + '; '.join(errors))

    week_count = len(weeks)
    if week_count != _EXPECTED_PLAN_WEEKS:
        errors.append(f'plan must contain {_EXPECTED_PLAN_WEEKS} weeks, found {week_count}')

    canonical_start = _ensure_date(block_start_date)
    if canonical_start is None and weeks:
        canonical_start = _ensure_date(weeks[0].get('start_date'))
    if canonical_start is None:
        errors.append('unable to determine canonical start date for plan')

    expected_days = set(_EXPECTED_TRAINING_DAYS)

    for idx, week in enumerate(weeks, start=1):
        prefix = f'week {idx}'
        week_number = week.get('week_number')
        if week_number != idx:
            errors.append(f'{prefix}: expected week_number {idx}, found {week_number}')

        week_start = _ensure_date(week.get('start_date'))
        if week_start is None:
            errors.append(f'{prefix}: missing or invalid start_date')
        elif canonical_start is not None:
            expected = canonical_start + timedelta(days=(idx - 1) * 7)
            if week_start != expected:
                errors.append(
                    f"{prefix}: start_date {week_start.isoformat()} does not match expected {expected.isoformat()}"
                )

        workouts = week.get('workouts')
        if not isinstance(workouts, list) or not workouts:
            errors.append(f'{prefix}: no workouts defined')
            continue

        training_days: set[int] = set()
        main_days: Dict[int, int] = {}
        invalid_day_flagged = False

        for workout in workouts:
            if not isinstance(workout, dict):
                continue
            day_raw = workout.get('day_of_week')
            try:
                day = int(day_raw)
            except (TypeError, ValueError):
                if not invalid_day_flagged:
                    errors.append(f'{prefix}: encountered invalid day_of_week value {day_raw!r}')
                    invalid_day_flagged = True
                continue

            slot_raw = workout.get('slot')
            slot = str(slot_raw).lower() if slot_raw is not None else ''
            if slot == 'conditioning':
                continue

            training_days.add(day)
            if slot == 'main':
                main_days[day] = main_days.get(day, 0) + 1

        missing_days = sorted(expected_days - training_days)
        if missing_days:
            errors.append(
                f"{prefix}: missing training days ({_format_day_list(missing_days)}); expected Monday/Tuesday/Thursday/Friday pattern"
            )
        extra_days = sorted(training_days - expected_days)
        if extra_days:
            errors.append(
                f"{prefix}: unexpected training days ({_format_day_list(extra_days)}); expected Monday/Tuesday/Thursday/Friday pattern"
            )

        for day in sorted(training_days & expected_days):
            if main_days.get(day, 0) == 0:
                errors.append(
                    f"{prefix}: {_DAY_NAME_BY_NUMBER.get(day, str(day))} session missing main lift slot"
                )

    balance = ensure_muscle_balance(plan)
    if not balance.balanced:
        missing_groups = ', '.join(balance.missing_groups) if balance.missing_groups else 'none'
        errors.append(
            'plan failed muscle balance check: '
            + f'missing={missing_groups}; ratio={balance.imbalance_ratio:.2f}'
        )

    if errors:
        raise ValueError('Plan structure validation failed: ' + '; '.join(errors))


_READINESS_STATE_BY_SEVERITY: Dict[str, str] = {
    "none": "ready",
    "mild": "lagging",
    "moderate": "low",
    "severe": "critical",
}


def _build_readiness_tip(reasons: List[str], severity: str) -> Optional[str]:
    for reason in reasons:
        note = reason.lower()
        if "sleep" in note:
            return "Prioritise sleep tonight and keep sessions easy."
        if "resting" in note and "hr" in note:
            return "Stay aerobic-only today and add breathing work."
    if severity == "mild":
        return "Dial effort back a touch and stack light recovery habits."
    if severity == "moderate":
        return "Keep intensity low and give yourself extra warm-up and cool-down."
    if severity == "severe":
        return "Swap intense work for pure recovery until metrics rebound."
    return None


def _build_readiness_summary(rec: BackoffRecommendation) -> ReadinessSummary:
    severity = rec.severity or "none"
    state = _READINESS_STATE_BY_SEVERITY.get(severity, "ready")
    metrics = rec.metrics if isinstance(rec.metrics, dict) else {}
    ratio_raw = metrics.get("severity_ratio", 0.0)
    try:
        breach_ratio = float(ratio_raw)
    except (TypeError, ValueError):
        breach_ratio = 0.0
    reasons = list(rec.reasons)
    if not rec.needs_backoff:
        headline = "Recovery steady"
        tip = None
        state = "ready"
    else:
        headline = f"Recovery dip detected ({severity})"
        tip = _build_readiness_tip(reasons, severity)
    return ReadinessSummary(
        state=state,
        headline=headline,
        tip=tip,
        severity=severity,
        breach_ratio=breach_ratio,
        reasons=reasons,
    )



def _collect_series(
    rows: Iterable[Dict[str, Any]],
    key: str,
    treat_zero_as_missing: bool = False,
) -> List[Tuple[date, float]]:
    """Extract a (date, value) series from historical rows."""
    out: List[Tuple[date, float]] = []
    for r in rows:
        d = r.get("date")
        v = r.get(key)
        if d is None:
            continue
        if v is None:
            continue
        if treat_zero_as_missing and isinstance(v, (int, float)) and v == 0:
            continue
        try:
            out.append((d, float(v)))
        except Exception:
            continue
    # sort by date ascending for predictable slicing
    out.sort(key=lambda x: x[0])
    return out


def _detect_metric_key(rows: Iterable[Dict[str, Any]], candidates: Tuple[str, ...]) -> Optional[str]:
    """Return the first metric key present in rows from the candidate list."""
    for row in rows:
        for key in candidates:
            value = row.get(key) if isinstance(row, dict) else None
            if value is None:
                continue
            try:
                float(value)
            except (TypeError, ValueError):
                continue
            return key
    return None


def _slice_values_in_window(
    series: List[Tuple[date, float]],
    start: date,
    end: date,
) -> List[float]:
    """Return values with start <= date <= end."""
    vals: List[float] = [v for (d, v) in series if start <= d <= end]
    return vals


def _window_stats(
    series: List[Tuple[date, float]], end: date, window_days: int
) -> Optional[WindowStats]:
    start = end - timedelta(days=window_days - 1)
    vals = _slice_values_in_window(series, start, end)
    if len(vals) < _MIN_DAYS_PER_WINDOW:
        return None
    return WindowStats(
        days=len(vals),
        start=start,
        end=end,
        values=vals,
        median_value=median(vals),
        mean_value=mean(vals),
    )


def _weighted_baseline(
    stats_by_window: Dict[int, WindowStats],
    weights: Dict[int, float],
) -> Optional[float]:
    """Combine medians across available windows using provided weights."""
    # normalise to available windows
    available = {w: stats_by_window[w].median_value for w in stats_by_window.keys()}
    if not available:
        return None
    weight_sum = sum(weights.get(w, 0.0) for w in available.keys())
    if weight_sum <= 0:
        # fall back to simple median of medians
        return median(list(available.values()))
    return sum(available[w] * (weights.get(w, 0.0) / weight_sum) for w in available.keys())


def _compute_baseline_for_metric(
    rows: List[Dict[str, Any]],
    key: str,
    end: date,
    treat_zero_as_missing: bool = False,
) -> BaselineResult:
    """
    Build a dynamic baseline for a metric using rolling windows.
    Uses medians per window, then a weighted blend favouring recency.
    """
    series = _collect_series(rows, key, treat_zero_as_missing=treat_zero_as_missing)
    by_window: Dict[int, WindowStats] = {}
    for w in _BASELINE_WINDOWS_DAYS:
        ws = _window_stats(series, end, w)
        if ws:
            by_window[w] = ws

    # favour recency, but include longer-term stability
    weights = {30: 0.40, 60: 0.30, 90: 0.20, 180: 0.10}
    baseline_value = _weighted_baseline(by_window, weights)
    return BaselineResult(value=baseline_value, by_window=by_window)


def _average_over_last_n_days(
    rows: List[Dict[str, Any]],
    key: str,
    end: date,
    days: int,
    require_min_points: int = 4,
    treat_zero_as_missing: bool = False,
) -> Optional[float]:
    """Average of last N days up to 'end'. Returns None if insufficient points."""
    series = _collect_series(rows, key, treat_zero_as_missing=treat_zero_as_missing)
    start = end - timedelta(days=days - 1)
    vals = _slice_values_in_window(series, start, end)
    if len(vals) < require_min_points:
        return None
    return mean(vals)


def _severity_from_breach_ratio(ratio: float) -> Tuple[str, float, int]:
    """
    Map a breach ratio to severity and recommended adjustments.
    ratio == 0 means within thresholds. 1.0 means exactly at threshold.
    """
    if ratio <= 0:
        return "none", 1.00, 0
    if 0 < ratio <= 1.0:
        return "mild", 0.90, 1
    if 1.0 < ratio <= 2.0:
        return "moderate", 0.80, 2
    return "severe", 0.70, 3


def compute_dynamic_baselines(
    dal: Any,
    reference_end_date: date,
    *,
    hrv_key: Optional[str] = None,
) -> Dict[str, BaselineResult]:
    """
    Compute dynamic baselines for RHR, Sleep, and (optionally) HRV as of 'reference_end_date'.
    Pull one 180-day history then reuse for each window computation.
    """
    start = reference_end_date - timedelta(days=max(_BASELINE_WINDOWS_DAYS) - 1)
    hist = dal.get_historical_data(start_date=start, end_date=reference_end_date)

    # RHR: zeros should generally be treated as missing
    rhr = _compute_baseline_for_metric(
        hist, key="hr_resting", end=reference_end_date, treat_zero_as_missing=True
    )
    # Sleep is in minutes. Zeros are likely missing, treat as missing.
    sleep = _compute_baseline_for_metric(
        hist, key="sleep_total_minutes", end=reference_end_date, treat_zero_as_missing=True
    )

    resolved_hrv_key = hrv_key or _detect_metric_key(hist, _HRV_METRIC_KEYS)
    if resolved_hrv_key:
        hrv = _compute_baseline_for_metric(
            hist,
            key=resolved_hrv_key,
            end=reference_end_date,
            treat_zero_as_missing=True,
        )
    else:
        hrv = BaselineResult(value=None, by_window={})

    return {"hr_resting": rhr, "sleep_total_minutes": sleep, "hrv": hrv}


def assess_recovery_and_backoff(
    dal: Any,
    week_start_date: date,
) -> BackoffRecommendation:
    """
    Evaluate the prior week versus dynamic baselines and propose a global back-off.
    Observation window is the last 7 complete days ending the day before 'week_start_date'.
    """
    obs_end = week_start_date - timedelta(days=1)
    obs_start = obs_end - timedelta(days=_LAST_N_DAYS_FOR_OBS - 1)

    # Pull just enough history for obs + baseline
    base_start = obs_end - timedelta(days=max(_BASELINE_WINDOWS_DAYS) - 1)
    hist = dal.get_historical_data(start_date=base_start, end_date=obs_end)

    hrv_metric_key = _detect_metric_key(hist, _HRV_METRIC_KEYS)

    avg_rhr_7d = _average_over_last_n_days(
        hist,
        key="hr_resting",
        end=obs_end,
        days=_LAST_N_DAYS_FOR_OBS,
        treat_zero_as_missing=True,
    )
    avg_sleep_7d = _average_over_last_n_days(
        hist,
        key="sleep_total_minutes",
        end=obs_end,
        days=_LAST_N_DAYS_FOR_OBS,
        treat_zero_as_missing=True,
    )
    avg_hrv_7d = None
    if hrv_metric_key:
        avg_hrv_7d = _average_over_last_n_days(
            hist,
            key=hrv_metric_key,
            end=obs_end,
            days=_LAST_N_DAYS_FOR_OBS,
            treat_zero_as_missing=True,
        )

    baselines = compute_dynamic_baselines(dal, reference_end_date=obs_end, hrv_key=hrv_metric_key)
    rhr_base = baselines["hr_resting"].value
    sleep_base = baselines["sleep_total_minutes"].value
    hrv_baseline_result = baselines.get("hrv")
    hrv_base = hrv_baseline_result.value if hrv_baseline_result else None

    reasons: List[str] = []
    breach_ratios: List[float] = []

    # Thresholds come from settings and remain percentage deltas
    rhr_allowed_inc = float(getattr(settings, "RHR_ALLOWED_INCREASE", 0.05))
    sleep_allowed_dec = float(getattr(settings, "SLEEP_ALLOWED_DECREASE", 0.10))
    hrv_allowed_dec = float(getattr(settings, "HRV_ALLOWED_DECREASE", 0.12))

    # RHR breach ratio
    if avg_rhr_7d is not None and rhr_base and rhr_base > 0:
        rhr_excess = (avg_rhr_7d - rhr_base) / rhr_base
        rhr_ratio = max(0.0, rhr_excess / rhr_allowed_inc) if rhr_allowed_inc > 0 else 0.0
        if rhr_ratio > 0:
            reasons.append(
                f"Resting HR {avg_rhr_7d:.1f} exceeds baseline {rhr_base:.1f} by {rhr_excess*100:.1f}%"
            )
        breach_ratios.append(rhr_ratio)
    else:
        breach_ratios.append(0.0)

    # Sleep breach ratio
    if avg_sleep_7d is not None and sleep_base and sleep_base > 0:
        sleep_deficit = (sleep_base - avg_sleep_7d) / sleep_base
        sleep_ratio = max(0.0, sleep_deficit / sleep_allowed_dec) if sleep_allowed_dec > 0 else 0.0
        if sleep_ratio > 0:
            reasons.append(
                f"Sleep {avg_sleep_7d:.0f} min below baseline {sleep_base:.0f} min by {sleep_deficit*100:.1f}%"
            )
        breach_ratios.append(sleep_ratio)
    else:
        breach_ratios.append(0.0)

    hrv_ratio = 0.0
    hrv_drop_pct: Optional[float] = None
    if avg_hrv_7d is not None and hrv_base and hrv_base > 0:
        hrv_drop_pct = (hrv_base - avg_hrv_7d) / hrv_base
        if hrv_allowed_dec > 0:
            hrv_ratio = max(0.0, hrv_drop_pct / hrv_allowed_dec)
        else:
            hrv_ratio = max(0.0, hrv_drop_pct)
        if hrv_ratio > 0:
            reasons.append(
                f"HRV {avg_hrv_7d:.1f} ms below baseline {hrv_base:.1f} ms by {hrv_drop_pct*100:.1f}%"
            )
        breach_ratios.append(hrv_ratio)
    else:
        breach_ratios.append(0.0)

    overall_ratio = max(breach_ratios) if breach_ratios else 0.0
    severity, set_multiplier, rir_increment = _severity_from_breach_ratio(overall_ratio)

    needs_backoff = severity != "none"

    metrics = {
        "obs_window": {"start": obs_start, "end": obs_end, "days": _LAST_N_DAYS_FOR_OBS},
        "avg_rhr_7d": avg_rhr_7d,
        "avg_sleep_7d": avg_sleep_7d,
        "avg_hrv_7d": avg_hrv_7d,
        "rhr_baseline": rhr_base,
        "sleep_baseline": sleep_base,
        "hrv_baseline": hrv_base,
        "rhr_allowed_increase": rhr_allowed_inc,
        "sleep_allowed_decrease": sleep_allowed_dec,
        "hrv_allowed_decrease": hrv_allowed_dec,
        "severity_ratio": overall_ratio,
        "hrv_severity_ratio": hrv_ratio,
        "hrv_metric_key": hrv_metric_key,
        "hrv_drop_ratio": hrv_drop_pct,
        "baselines_detail": {
            "rhr_by_window": {
                w: {"start": s.start, "end": s.end, "days": s.days, "median": s.median_value}
                for w, s in baselines["hr_resting"].by_window.items()
            },
            "sleep_by_window": {
                w: {"start": s.start, "end": s.end, "days": s.days, "median": s.median_value}
                for w, s in baselines["sleep_total_minutes"].by_window.items()
            },
            "hrv_by_window": (
                {
                    w: {"start": s.start, "end": s.end, "days": s.days, "median": s.median_value}
                    for w, s in hrv_baseline_result.by_window.items()
                }
                if hrv_baseline_result and hrv_baseline_result.by_window
                else {}
            ),
        },
    }

    return BackoffRecommendation(
        needs_backoff=needs_backoff,
        severity=severity,
        reasons=reasons,
        set_multiplier=set_multiplier,
        rir_increment=rir_increment,
        metrics=metrics,
    )


def summarise_readiness(dal: Any, week_start_date: date) -> ReadinessSummary:
    """Return a non-destructive readiness summary for the supplied window."""
    rec = assess_recovery_and_backoff(dal, week_start_date)
    return _build_readiness_summary(rec)


def validate_and_adjust_plan(dal: Any, week_start_date: date) -> ValidationDecision:
    """Assess recovery ahead of the upcoming week and optionally apply plan adjustments."""

    rec = assess_recovery_and_backoff(dal, week_start_date)
    readiness = _build_readiness_summary(rec)

    adherence = _evaluate_adherence_adjustment(dal, week_start_date, rec)

    final_multiplier = rec.set_multiplier * adherence.get('set_multiplier', 1.0)
    final_multiplier = max(0.60, min(1.20, final_multiplier))
    final_rir_increment = rec.rir_increment + adherence.get('rir_adjust', 0)

    combined_reasons = list(rec.reasons)
    combined_reasons.extend(adherence.get('reasons', []))

    metrics = copy.deepcopy(rec.metrics) if isinstance(rec.metrics, dict) else {}
    metrics['adherence'] = adherence.get('metrics', {'available': False})

    rec = replace(
        rec,
        set_multiplier=final_multiplier,
        rir_increment=final_rir_increment,
        reasons=combined_reasons,
        metrics=metrics,
    )

    adherence_log_entries = adherence.get('log_entries', [])
    set_delta = abs(final_multiplier - 1.0)
    rir_delta = final_rir_increment != 0
    should_apply = rec.needs_backoff or set_delta >= 0.01 or rir_delta

    if not should_apply:
        explanation = "Recovery within dynamic baselines - no global back-off applied."
        if adherence.get('direction') != 'maintain' and adherence.get('reasons'):
            notes = '; '.join(adherence['reasons'])
            explanation = f"Recovery within dynamic baselines - no plan change applied. Notes: {notes}"
        log_utils.log_message(explanation, 'INFO')
        log_entries = list(adherence_log_entries)
        return ValidationDecision(
            needs_backoff=rec.needs_backoff,
            applied=False,
            explanation=explanation,
            log_entries=log_entries,
            readiness=readiness,
            recommendation=rec,
        )

    log_entries: List[str] = [
        f"severity={rec.severity}",
        f"set_multiplier={final_multiplier:.2f}",
        f"rir_increment={final_rir_increment}",
        *combined_reasons,
        *adherence_log_entries,
    ]
    if readiness.tip:
        log_entries.append(f"readiness_tip={readiness.tip}")

    if rec.needs_backoff:
        reason_text = ', '.join(combined_reasons) or 'thresholds exceeded'
        explanation = (
            f"Global back-off recommended, severity={rec.severity}, "
            f"set_multiplier={final_multiplier:.2f}, RIR+={final_rir_increment}. "
            f"Reasons: {reason_text}."
        )
        log_level = 'WARNING'
    else:
        if adherence.get('direction') == 'reduce':
            explanation = (
                f"Adherence below target; scaling sets by {final_multiplier:.2f} with recovery steady."
            )
        elif adherence.get('direction') == 'increase':
            explanation = (
                f"High adherence with strong recovery; scaling sets by {final_multiplier:.2f}."
            )
        else:
            explanation = 'Applying plan adjustment with recovery steady.'
        if combined_reasons:
            explanation += f" Reasons: {', '.join(combined_reasons)}."
        log_level = 'INFO'

    log_utils.log_message(explanation, log_level)

    applied = False
    apply_fn = getattr(dal, 'apply_plan_backoff', None)
    if callable(apply_fn):
        try:
            apply_fn(
                week_start_date,
                set_multiplier=final_multiplier,
                rir_increment=final_rir_increment,
            )
            log_utils.log_message('Applied plan adjustment to upcoming week.', 'INFO')
            applied = True
        except Exception as exc:  # pragma: no cover - DB failures are environment-specific
            log_utils.log_message(f'Failed to apply back-off: {exc}', 'ERROR')
            log_entries.append(f'apply_failed: {exc}')
    else:
        log_utils.log_message(
            "DAL has no 'apply_plan_backoff' - no DB changes performed. "
            'Downstream components may apply this recommendation explicitly.',
            'WARN',
        )
        log_entries.append('dal_missing_backoff')

    return ValidationDecision(
        needs_backoff=rec.needs_backoff,
        applied=applied,
        explanation=explanation,
        log_entries=log_entries,
        readiness=readiness,
        recommendation=rec,
    )

