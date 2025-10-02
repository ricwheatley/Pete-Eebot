# pete_e/infrastructure/weekly_reviewer_v2.py
#
# Weekly reviewer that:
#  - refreshes MVs (optional),
#  - computes recovery vs baseline and adherence vs planned,
#  - applies bounded adjustments to the UPCOMING week,
#  - exports that week to Wger,
#  - posts a concise Telegram summary (if tokens provided).
#
# Policy:
#  - Recovery thresholds: RHR +5/+7.5/+10 percent, Sleep -10/-15/-20 percent -> mild/moderate/severe.
#  - Adherence: executed/planned <70 percent across 2+ muscles or overall <70 percent -> reduce volume.
#               70-90 percent -> maintain.
#               >110 percent with good recovery -> increase volume (prefer volume over intensity).
#  - Bounds: volume (sets) ±20 percent, intensity (percent_1rm) ±5 percent absolute.
#
# Env:
#   DATABASE_URL
#   TELEGRAM_TOKEN (optional)
#   TELEGRAM_CHAT_ID (optional)
#   WGER_API_KEY (optional for real exports; payloads still logged without it)
#
# Exporter v3 (your v4 implementation) extra env toggles:
#   WGER_DRY_RUN           -> "true"/"1" to validate and log only, no API calls
#   WGER_FORCE_OVERWRITE   -> "true"/"1" to wipe days for the target week before export
#   WGER_EXPORT_DEBUG      -> "true"/"1" to log request/response bodies at DEBUG level
#   WGER_BLAZE_MODE        -> "exercise" (default) or "comment"
#   WGER_ROUTINE_PREFIX    -> optional prefix for routine names (e.g. "Mesocycle A")
#

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import requests

from pete_e.infrastructure.plan_rw import (
    conn_cursor,
    get_active_plan,
    get_week_ids_for_plan,
    adjust_sets_only,
    adjust_rir,
    adjust_main_lifts_intensity,
    build_week_payload,
)
from pete_e.domain.schedule_rules import SQUAT_ID, BENCH_ID, DEADLIFT_ID, OHP_ID
# Note: you've overwritten v3 with the new implementation, so keep this import path.
from pete_e.infrastructure.wger_exporter import export_week_to_wger
from pete_e.config import get_env, settings

MAIN_LIFTS = (SQUAT_ID, BENCH_ID, DEADLIFT_ID, OHP_ID)

RHR_THRESH = (5.0, 7.5, 10.0)      # mild, moderate, severe (% above baseline)
SLEEP_THRESH = (10.0, 15.0, 20.0)  # mild, moderate, severe (% below baseline)

VOL_CAP_DOWN = 0.80
VOL_CAP_UP = 1.20
INTENSITY_CAP_DOWN = -5.0
INTENSITY_CAP_UP = 5.0


def _bool_env(name: str, default: bool = False) -> bool:
    val = get_env(name, default=default)
    if isinstance(val, bool):
        return val
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")


@dataclass
class ReviewInputs:
    plan_id: int
    start_date: date
    weeks: int
    upcoming_week_no: int
    last_week_start: date
    last_week_end: date


@dataclass
class ReviewDecision:
    set_multiplier: float = 1.0
    rir_delta: float = 0.0
    intensity_delta_abs: float = 0.0
    reasons: List[str] = None

    def clamp(self):
        self.set_multiplier = max(VOL_CAP_DOWN, min(VOL_CAP_UP, self.set_multiplier))
        self.intensity_delta_abs = max(INTENSITY_CAP_DOWN, min(INTENSITY_CAP_UP, self.intensity_delta_abs))
        if self.reasons is None:
            self.reasons = []


def _next_monday(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


def _make_inputs(today: date) -> Optional[ReviewInputs]:
    ap = get_active_plan()
    if not ap:
        return None
    start = ap["start_date"]
    weeks = ap["weeks"]
    plan_id = ap["id"]

    upcoming_mon = _next_monday(today)
    # Compute upcoming week number relative to plan start (which we align to Mondays)
    if upcoming_mon < start:
        return None
    upcoming_week_no = 1 + ((upcoming_mon - start).days // 7)
    if upcoming_week_no < 1 or upcoming_week_no > weeks:
        return None  # outside this plan window

    last_week_start = upcoming_mon - timedelta(days=7)
    last_week_end = upcoming_mon - timedelta(days=1)

    return ReviewInputs(
        plan_id=plan_id,
        start_date=start,
        weeks=weeks,
        upcoming_week_no=upcoming_week_no,
        last_week_start=last_week_start,
        last_week_end=last_week_end,
    )


def _refresh_mvs_concurrently():
    with conn_cursor() as (_, cur):
        for mv in ("plan_muscle_volume", "actual_muscle_volume"):
            try:
                cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv};")
            except Exception:
                # Fallback to blocking if concurrent not available
                cur.execute(f"REFRESH MATERIALIZED VIEW {mv};")


def _fetch_recovery_metrics(last_week_start: date, last_week_end: date) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Returns (avg_rhr, base_rhr, avg_sleep, base_sleep) from daily_summary.
    Baseline computed over previous 60 days excluding the last week. Fallbacks to overall mean if needed.
    """
    with conn_cursor() as (_, cur):
        cur.execute(
            """
            WITH last7 AS (
                SELECT avg(hr_resting)::float AS avg_rhr,
                       avg(sleep_asleep_minutes)::float AS avg_sleep
                FROM daily_summary
                WHERE date BETWEEN %s AND %s
            ),
            base AS (
                SELECT avg(hr_resting)::float AS base_rhr,
                       avg(sleep_asleep_minutes)::float AS base_sleep
                FROM daily_summary
                WHERE date BETWEEN %s AND %s
            ),
            fallback AS (
                SELECT avg(hr_resting)::float AS all_rhr,
                       avg(sleep_asleep_minutes)::float AS all_sleep
                FROM daily_summary
            )
            SELECT
                l.avg_rhr,
                COALESCE(b.base_rhr, f.all_rhr) AS base_rhr,
                l.avg_sleep,
                COALESCE(b.base_sleep, f.all_sleep) AS base_sleep
            FROM last7 l, base b, fallback f;
            """,
            (
                last_week_start, last_week_end,
                last_week_start - timedelta(days=60), last_week_start - timedelta(days=1),
            ),
        )
        row = cur.fetchone()
        return row["avg_rhr"], row["base_rhr"], row["avg_sleep"], row["base_sleep"]


def _recovery_decision(avg_rhr, base_rhr, avg_sleep, base_sleep) -> Tuple[str, float, float, List[str]]:
    """
    Returns (severity, set_multiplier, rir_delta, reasons)
    """
    reasons: List[str] = []
    severity = "none"
    set_mult = 1.0
    rir_delta = 0.0

    # Compute breaches in percent
    rhr_breach = 0.0
    sleep_breach = 0.0
    if avg_rhr is not None and base_rhr and base_rhr > 0:
        rhr_breach = max(0.0, (avg_rhr - base_rhr) / base_rhr * 100.0)
    if avg_sleep is not None and base_sleep and base_sleep > 0:
        sleep_breach = max(0.0, (base_sleep - avg_sleep) / base_sleep * 100.0)

    # Determine severity
    if rhr_breach >= RHR_THRESH[2] or sleep_breach >= SLEEP_THRESH[2]:
        severity = "severe"; set_mult = 0.70; rir_delta = 3.0
    elif rhr_breach >= RHR_THRESH[1] or sleep_breach >= SLEEP_THRESH[1]:
        severity = "moderate"; set_mult = 0.80; rir_delta = 2.0
    elif rhr_breach >= RHR_THRESH[0] or sleep_breach >= SLEEP_THRESH[0]:
        severity = "mild"; set_mult = 0.90; rir_delta = 1.0
    else:
        severity = "none"; set_mult = 1.0; rir_delta = 0.0

    if avg_rhr is not None and base_rhr is not None:
        reasons.append(f"RHR {avg_rhr:.1f} vs baseline {base_rhr:.1f} (+{rhr_breach:.1f} percent)")
    if avg_sleep is not None and base_sleep is not None:
        reasons.append(f"Sleep {avg_sleep:.0f} min vs baseline {base_sleep:.0f} (-{sleep_breach:.1f} percent deficit)")

    return severity, set_mult, rir_delta, reasons


def _fetch_planned_vs_actual(plan_id: int, week_no: int, last_week_start: date, last_week_end: date) -> Tuple[Dict[int, float], Dict[int, float]]:
    """
    Returns (planned_by_muscle, actual_by_muscle) in kg for the last completed week.
    """
    planned: Dict[int, float] = {}
    actual: Dict[int, float] = {}

    with conn_cursor() as (_, cur):
        # Planned
        cur.execute(
            """
            SELECT muscle_id, target_volume_kg
            FROM plan_muscle_volume
            WHERE plan_id = %s AND week_number = %s;
            """,
            (plan_id, week_no),
        )
        for r in cur.fetchall():
            if r["muscle_id"] is not None:
                planned[r["muscle_id"]] = float(r["target_volume_kg"] or 0)

        # Actual over the date range
        cur.execute(
            """
            SELECT muscle_id, SUM(actual_volume_kg)::float AS actual_kg
            FROM actual_muscle_volume
            WHERE date BETWEEN %s AND %s
            GROUP BY muscle_id;
            """,
            (last_week_start, last_week_end),
        )
        for r in cur.fetchall():
            if r["muscle_id"] is not None:
                actual[r["muscle_id"]] = float(r["actual_kg"] or 0)

    return planned, actual


def _adherence_decision(planned: Dict[int, float], actual: Dict[int, float], recovery_severity: str) -> Tuple[str, float, float, List[str]]:
    """
    Returns (direction, set_multiplier_adj, intensity_delta_abs, reasons)
    direction in {'increase','reduce','maintain'}
    """
    reasons: List[str] = []
    planned_total = sum(planned.values())
    actual_total = sum(actual.get(m, 0.0) for m in planned.keys())
    ratio = (actual_total / planned_total) if planned_total > 0 else 1.0

    # Count low/high groups
    low_groups = sum(1 for m, pv in planned.items() if pv > 0 and (actual.get(m, 0.0) / pv) < 0.70)
    high_groups = sum(1 for m, pv in planned.items() if pv > 0 and (actual.get(m, 0.0) / pv) > 1.10)

    reasons.append(f"Executed vs planned volume ratio {ratio:.2f}; low groups {low_groups}, high groups {high_groups}")

    direction = "maintain"
    set_mult_adj = 1.0
    intensity_delta = 0.0

    if ratio < 0.70 or low_groups >= 2:
        direction = "reduce"
        set_mult_adj = 0.80
        intensity_delta = -2.5  # small absolute decrease if needed
        reasons.append("Adherence low, reducing next week volume and easing intensity slightly")
    elif ratio > 1.10 and recovery_severity == "none":
        direction = "increase"
        set_mult_adj = 1.10  # prefer volume increase over intensity
        intensity_delta = 0.0
        reasons.append("Adherence high with good recovery, increasing volume slightly")
    elif 0.70 <= ratio <= 0.90:
        direction = "maintain"
        set_mult_adj = 1.0
        intensity_delta = 0.0
        reasons.append("Within target range, maintaining")

    return direction, set_mult_adj, intensity_delta, reasons


def _post_telegram(text: str):
    token = settings.TELEGRAM_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception:
        pass


def review_and_apply(today: Optional[date] = None, refresh_mvs: bool = True) -> Optional[Dict[str, str]]:
    """
    Main entrypoint. Returns a summary dict, or None if no action required.
    """
    if today is None:
        today = date.today()

    inputs = _make_inputs(today)
    if not inputs:
        return None

    # Do not adjust before week 1 starts
    if inputs.upcoming_week_no == 1:
        return {
            "status": "skipped",
            "reason": "Upcoming is week 1, no prior week to review",
            "plan_id": str(inputs.plan_id),
            "upcoming_week": str(inputs.upcoming_week_no),
        }

    if refresh_mvs:
        _refresh_mvs_concurrently()

    # Recovery slice
    avg_rhr, base_rhr, avg_sleep, base_sleep = _fetch_recovery_metrics(inputs.last_week_start, inputs.last_week_end)
    rec_sev, rec_set_mult, rec_rir_delta, rec_reasons = _recovery_decision(avg_rhr, base_rhr, avg_sleep, base_sleep)

    # Adherence slice
    planned, actual = _fetch_planned_vs_actual(inputs.plan_id, inputs.upcoming_week_no - 1, inputs.last_week_start, inputs.last_week_end)
    adh_dir, adh_set_mult, adh_intensity_delta, adh_reasons = _adherence_decision(planned, actual, rec_sev)

    # Combine decisions with bounds
    decision = ReviewDecision(set_multiplier=rec_set_mult, rir_delta=rec_rir_delta, intensity_delta_abs=0.0, reasons=[])
    # Apply adherence effect
    decision.set_multiplier *= adh_set_mult
    # Only add intensity delta if we did not already back off severely
    if rec_sev in ("moderate", "severe") and adh_dir == "increase":
        # Do not increase intensity when recovery is not good
        pass
    else:
        decision.intensity_delta_abs += adh_intensity_delta

    decision.reasons = [f"Recovery: {rec_sev}"] + rec_reasons + adh_reasons
    decision.clamp()

    # Apply to DB - upcoming week rows
    week_ids = get_week_ids_for_plan(inputs.plan_id)
    upcoming_week_id = week_ids.get(inputs.upcoming_week_no)
    if not upcoming_week_id:
        return None

    # Sets
    adjust_sets_only(upcoming_week_id, decision.set_multiplier)
    # RIR only if positive delta (we do not reduce RIR automatically)
    if decision.rir_delta > 0:
        adjust_rir(upcoming_week_id, decision.rir_delta)
    # Intensity tweak for main lifts only
    if abs(decision.intensity_delta_abs) > 0:
        adjust_main_lifts_intensity(upcoming_week_id, decision.intensity_delta_abs, MAIN_LIFTS)

    # Export to Wger
    week_payload = build_week_payload(inputs.plan_id, inputs.upcoming_week_no)

    # Exporter options via env
    dry_run = _bool_env("WGER_DRY_RUN", settings.WGER_DRY_RUN)
    force_overwrite = _bool_env("WGER_FORCE_OVERWRITE", settings.WGER_FORCE_OVERWRITE)
    debug_api = _bool_env("WGER_EXPORT_DEBUG", settings.WGER_EXPORT_DEBUG)
    blaze_mode = str(get_env("WGER_BLAZE_MODE", default=settings.WGER_BLAZE_MODE)).strip().lower()
    if blaze_mode not in ("exercise", "comment"):
        blaze_mode = "exercise"
    routine_prefix = get_env("WGER_ROUTINE_PREFIX", default=settings.WGER_ROUTINE_PREFIX)  # optional

    export_res = export_week_to_wger(
        week_payload,
        week_start=inputs.last_week_end + timedelta(days=1),
        routine_prefix=routine_prefix,
        force_overwrite=force_overwrite,
        blaze_mode=blaze_mode,
        debug_api=debug_api,
        dry_run=dry_run,
    )

    # Telegram summary
    summary_lines = [
        f"Weekly review complete for plan {inputs.plan_id}, week {inputs.upcoming_week_no}.",
        f"Set multiplier {decision.set_multiplier:.2f}, RIR delta {decision.rir_delta:+.1f}, intensity delta {decision.intensity_delta_abs:+.1f} percent on main lifts.",
        f"Window reviewed {inputs.last_week_start} to {inputs.last_week_end}.",
    ] + decision.reasons
    _post_telegram("\n".join(summary_lines))

    export_status = "dry-run" if dry_run else ("ok" if export_res else "logged")
    return {
        "status": "applied",
        "plan_id": str(inputs.plan_id),
        "upcoming_week": str(inputs.upcoming_week_no),
        "set_multiplier": f"{decision.set_multiplier:.2f}",
        "rir_delta": f"{decision.rir_delta:+.1f}",
        "intensity_delta": f"{decision.intensity_delta_abs:+.1f}",
        "export": export_status,
    }
