# pete_e/domain/validation.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median, mean
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pete_e.config import settings
from pete_e.infrastructure import log_utils


# Windows are expressed in days to avoid calendar edge cases.
# 30, 60, 90 and 180 approximate the prior 1, 2, 3 and 6 months.
_BASELINE_WINDOWS_DAYS: List[int] = [30, 60, 90, 180]
_MIN_DAYS_PER_WINDOW: int = 14  # require at least this many points to trust a window
_LAST_N_DAYS_FOR_OBS: int = 7   # assess the most recent 7 days before the upcoming week


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
) -> Dict[str, BaselineResult]:
    """
    Compute dynamic baselines for RHR and Sleep as of 'reference_end_date'.
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
    return {"hr_resting": rhr, "sleep_total_minutes": sleep}


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

    avg_rhr_7d = _average_over_last_n_days(
        hist, key="hr_resting", end=obs_end, days=_LAST_N_DAYS_FOR_OBS,
        treat_zero_as_missing=True,
    )
    avg_sleep_7d = _average_over_last_n_days(
        hist, key="sleep_total_minutes", end=obs_end, days=_LAST_N_DAYS_FOR_OBS,
        treat_zero_as_missing=True,
    )

    baselines = compute_dynamic_baselines(dal, reference_end_date=obs_end)
    rhr_base = baselines["hr_resting"].value
    sleep_base = baselines["sleep_total_minutes"].value

    reasons: List[str] = []
    breach_ratios: List[float] = []

    # Thresholds come from settings and remain percentage deltas
    rhr_allowed_inc = float(getattr(settings, "RHR_ALLOWED_INCREASE", 0.05))
    sleep_allowed_dec = float(getattr(settings, "SLEEP_ALLOWED_DECREASE", 0.10))

    # RHR breach ratio
    if avg_rhr_7d is not None and rhr_base:
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
    if avg_sleep_7d is not None and sleep_base:
        sleep_deficit = (sleep_base - avg_sleep_7d) / sleep_base
        sleep_ratio = max(0.0, sleep_deficit / sleep_allowed_dec) if sleep_allowed_dec > 0 else 0.0
        if sleep_ratio > 0:
            reasons.append(
                f"Sleep {avg_sleep_7d:.0f} min below baseline {sleep_base:.0f} min by {sleep_deficit*100:.1f}%"
            )
        breach_ratios.append(sleep_ratio)
    else:
        breach_ratios.append(0.0)

    overall_ratio = max(breach_ratios) if breach_ratios else 0.0
    severity, set_multiplier, rir_increment = _severity_from_breach_ratio(overall_ratio)

    needs_backoff = severity != "none"

    metrics = {
        "obs_window": {"start": obs_start, "end": obs_end, "days": _LAST_N_DAYS_FOR_OBS},
        "avg_rhr_7d": avg_rhr_7d,
        "avg_sleep_7d": avg_sleep_7d,
        "rhr_baseline": rhr_base,
        "sleep_baseline": sleep_base,
        "rhr_allowed_increase": rhr_allowed_inc,
        "sleep_allowed_decrease": sleep_allowed_dec,
        "severity_ratio": overall_ratio,
        "baselines_detail": {
            "rhr_by_window": {
                w: {"start": s.start, "end": s.end, "days": s.days, "median": s.median_value}
                for w, s in baselines["hr_resting"].by_window.items()
            },
            "sleep_by_window": {
                w: {"start": s.start, "end": s.end, "days": s.days, "median": s.median_value}
                for w, s in baselines["sleep_total_minutes"].by_window.items()
            },
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
    """Assess recovery ahead of the upcoming week and optionally apply a back-off.

    Returns a structured decision detailing whether recovery warranted a back-off,
    if it was applied, and the reasoning captured for downstream logging.
    """
    rec = assess_recovery_and_backoff(dal, week_start_date)
    readiness = _build_readiness_summary(rec)

    if not rec.needs_backoff:
        explanation = (
            "Recovery within dynamic baselines - no global back-off applied."
        )
        log_utils.log_message(explanation, "INFO")
        return ValidationDecision(
            needs_backoff=False,
            applied=False,
            explanation=explanation,
            log_entries=[],
            readiness=readiness,
            recommendation=rec,
        )

    log_entries: List[str] = [
        f"severity={rec.severity}",
        f"set_multiplier={rec.set_multiplier:.2f}",
        f"rir_increment={rec.rir_increment}",
        *rec.reasons,
    ]
    if readiness.tip:
        log_entries.append(f"readiness_tip={readiness.tip}")

    explanation = (
        f"Global back-off recommended, severity={rec.severity}, "
        f"set_multiplier={rec.set_multiplier:.2f}, RIR+={rec.rir_increment}. "
        f"Reasons: {', '.join(rec.reasons) or 'thresholds exceeded'}."
    )
    log_utils.log_message(explanation, "WARNING")

    applied = False
    if hasattr(dal, "apply_plan_backoff"):
        try:
            dal.apply_plan_backoff(
                week_start_date,
                set_multiplier=rec.set_multiplier,
                rir_increment=rec.rir_increment,
            )
            log_utils.log_message("Applied global back-off to upcoming week.", "INFO")
            applied = True
        except Exception as exc:  # pragma: no cover - DB failures are environment-specific
            log_utils.log_message(f"Failed to apply back-off: {exc}", "ERROR")
            log_entries.append(f"apply_failed: {exc}")
    else:
        log_utils.log_message(
            "DAL has no 'apply_plan_backoff' - no DB changes performed. "
            "Downstream components may apply this recommendation explicitly.",
            "WARN",
        )
        log_entries.append("dal_missing_backoff")

    return ValidationDecision(
        needs_backoff=True,
        applied=applied,
        explanation=explanation,
        log_entries=log_entries,
        readiness=readiness,
        recommendation=rec,
    )
