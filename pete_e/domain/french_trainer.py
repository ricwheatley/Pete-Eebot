# -*- coding: utf-8 -*-

"""Narrative generation in Pierre's franglais coach voice."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

from pete_e.domain import phrase_picker
from pete_e.domain import logging as domain_logging
from pete_e.utils import converters, math as math_utils

MetricMap = Dict[str, Dict[str, Any]]
ContextMap = Dict[str, Any]


@dataclass
class Highlight:
    name: str
    score: float
    records: Set[str]
def _collect_records(stats: Mapping[str, Any]) -> Set[str]:
    records: Set[str] = set()
    latest = converters.to_float(stats.get("yesterday_value"))
    if latest is None:
        return records
    checks = {
        "all_time_high": "all_time_high",
        "all_time_low": "all_time_low",
        "six_month_high": "six_month_high",
        "six_month_low": "six_month_low",
        "three_month_high": "three_month_high",
        "three_month_low": "three_month_low",
    }
    for flag, column in checks.items():
        if math_utils.near(latest, converters.to_float(stats.get(column))):
            records.add(flag)
    return records


def _score_metric(name: str, stats: Mapping[str, Any]) -> Highlight:
    score = 0.0
    pct_change = converters.to_float(stats.get("pct_change_d1"))
    if pct_change is not None:
        score = max(score, abs(pct_change))
    week_change = converters.to_float(stats.get("pct_change_7d"))
    if week_change is not None:
        score = max(score, abs(week_change) * 0.8)
    abs_change = converters.to_float(stats.get("abs_change_d1"))
    if abs_change is not None:
        score = max(score, abs(abs_change))
    records = _collect_records(stats)
    if "all_time_high" in records or "all_time_low" in records:
        score += 75.0
    if "six_month_high" in records or "six_month_low" in records:
        score += 35.0
    if "three_month_high" in records or "three_month_low" in records:
        score += 20.0
    if name in {"weight", "resting_heart_rate"} and pct_change is not None:
        score += abs(pct_change) * 0.25
    return Highlight(name=name, score=score, records=records)


def _select_highlights(metrics: MetricMap, limit: int = 3) -> List[Highlight]:
    candidates = [_score_metric(name, stats) for name, stats in metrics.items()]
    candidates = [item for item in candidates if item.score > 0 or item.records]
    candidates.sort(key=lambda item: item.score, reverse=True)
    highlights = candidates[:limit]
    if highlights:
        return highlights
    fallback_order: Sequence[str] = (
        "weight",
        "resting_heart_rate",
        "steps",
        "sleep_hours",
        "strength_volume",
    )
    used: List[Highlight] = []
    for metric_name in fallback_order:
        stats = metrics.get(metric_name)
        if stats is None:
            continue
        used.append(_score_metric(metric_name, stats))
        if len(used) == min(limit, len(fallback_order)):
            break
    return used


def _format_delta(value: float | None, unit: str) -> str:
    if value is None or value == 0:
        return ""
    direction = "down" if value < 0 else "up"
    magnitude = abs(value)
    if unit == "kg":
        return f" {direction} {magnitude:.1f} kg"
    if unit == "%":
        return f" {direction} {magnitude:.1f}%"
    if unit == "bpm":
        return f" {direction} {magnitude:.0f} bpm"
    if unit == "hours":
        return f" {direction} {magnitude:.1f} h"
    if unit == "steps":
        return f" {direction} {magnitude:,.0f}"
    return f" {direction} {magnitude:.1f}"


def _record_suffix(records: Set[str]) -> str:
    if "all_time_low" in records:
        return " (nouveau record bas!)"
    if "all_time_high" in records:
        return " (nouveau record haut!)"
    if "three_month_low" in records:
        return " (lowest in 3 months)"
    if "three_month_high" in records:
        return " (highest in 3 months)"
    if "six_month_low" in records:
        return " (best in 6 months)"
    if "six_month_high" in records:
        return " (peak for 6 months)"
    return ""


def _build_weight_line(stats: Mapping[str, Any], records: Set[str]) -> str | None:
    value = converters.to_float(stats.get("yesterday_value"))
    if value is None:
        return None
    delta = converters.to_float(stats.get("abs_change_d1"))
    pieces = [f"**Weight:** {value:.1f} kg"]
    change_text = _format_delta(delta, "kg")
    if change_text:
        pieces.append(change_text.strip())
    pieces.append("C'est bien, on reste constant.")
    suffix = _record_suffix(records)
    if suffix:
        pieces[-1] += suffix
    return " ".join(pieces)


def _build_body_fat_line(stats: Mapping[str, Any], records: Set[str]) -> str | None:
    value = converters.to_float(stats.get("yesterday_value"))
    if value is None:
        return None
    delta = converters.to_float(stats.get("abs_change_d1"))
    direction = _format_delta(delta, "%")
    message = f"**Body Fat:** {value:.1f}%"
    if direction:
        message += direction
    suffix = _record_suffix(records)
    if suffix:
        message += suffix
    return message


def _build_muscle_line(stats: Mapping[str, Any], records: Set[str]) -> str | None:
    value = converters.to_float(stats.get("yesterday_value"))
    if value is None:
        return None
    delta = converters.to_float(stats.get("abs_change_d1"))
    message = f"**Muscle:** {value:.1f}%"
    if delta is not None and delta != 0:
        change = "up" if delta > 0 else "down"
        message += f" ({change} {abs(delta):.1f}% vs hier)"
    suffix = _record_suffix(records)
    if suffix:
        message += suffix
    return message


def _build_rhr_line(stats: Mapping[str, Any], records: Set[str]) -> str | None:
    value = converters.to_float(stats.get("yesterday_value"))
    if value is None:
        return None
    delta_pct = converters.to_float(stats.get("pct_change_d1"))
    delta_abs = converters.to_float(stats.get("abs_change_d1"))
    line = f"**Resting HR:** {value:.0f} bpm"
    if delta_pct is not None and delta_pct != 0:
        direction = "down" if delta_pct < 0 else "up"
        line += f" ({direction} {abs(delta_pct):.1f}% vs hier)"
    elif delta_abs is not None and delta_abs != 0:
        line += _format_delta(delta_abs, "bpm")
    if delta_pct is not None and delta_pct < 0:
        line += "  ton coeur recupere super bien!"
    suffix = _record_suffix(records)
    if suffix:
        line += suffix
    return line


def _build_steps_line(stats: Mapping[str, Any], records: Set[str]) -> str | None:
    value = converters.to_float(stats.get("yesterday_value"))
    if value is None:
        return None
    line = f"**Steps:** {int(round(value)):,} pas"
    delta_pct = converters.to_float(stats.get("pct_change_d1"))
    if delta_pct and abs(delta_pct) >= 10:
        direction = "up" if delta_pct > 0 else "down"
        line += f" ({direction} {abs(delta_pct):.0f}% vs hier)"
    suffix = _record_suffix(records)
    if suffix:
        line += suffix
    return line


def _build_sleep_line(stats: Mapping[str, Any], records: Set[str]) -> str | None:
    value = converters.to_float(stats.get("yesterday_value"))
    if value is None:
        return None
    line = f"**Sleep:** {value:.1f} h de sommeil"
    delta_pct = converters.to_float(stats.get("pct_change_d1"))
    if delta_pct and abs(delta_pct) >= 10:
        direction = "moins" if delta_pct < 0 else "plus"
        line += f" ({direction} {abs(delta_pct):.0f}% vs la nuit precedente)"
    suffix = _record_suffix(records)
    if suffix:
        line += suffix
    return line


def _build_strength_line(stats: Mapping[str, Any], records: Set[str]) -> str | None:
    value = converters.to_float(stats.get("yesterday_value"))
    if value is None:
        return None
    line = f"**Strength Volume:** {value:,.0f} kg total"
    delta = converters.to_float(stats.get("abs_change_d1"))
    if delta:
        direction = "plus" if delta > 0 else "moins"
        line += f" ({direction} {abs(delta):,.0f} kg vs session precedente)"
    suffix = _record_suffix(records)
    if suffix:
        line += suffix
    return line


def _build_squat_line(stats: Mapping[str, Any], records: Set[str]) -> str | None:
    value = converters.to_float(stats.get("yesterday_value"))
    previous = converters.to_float(stats.get("day_before_value"))
    if value is None:
        return None
    if value == 0 and (previous is None or previous == 0):
        return None
    if value == 0:
        return f"**Squat Volume:** Rest day pour les squats (dernier total {previous:,.0f} kg)."
    if previous is None or previous == 0:
        line = f"**Squat Volume:** {value:,.0f} kg - retour sous la barre!"
    else:
        delta = value - previous
        direction = "up" if delta > 0 else "down"
        line = f"**Squat Volume:** {value:,.0f} kg ({direction} {abs(delta):,.0f} kg vs derniere seance)."
    suffix = _record_suffix(records)
    if suffix:
        line += suffix
    return line


_BUILDER_MAP = {
    "weight": _build_weight_line,
    "body_fat_pct": _build_body_fat_line,
    "muscle_pct": _build_muscle_line,
    "resting_heart_rate": _build_rhr_line,
    "steps": _build_steps_line,
    "sleep_hours": _build_sleep_line,
    "strength_volume": _build_strength_line,
    "squat_volume": _build_squat_line,
}


def _build_generic_line(name: str, stats: Mapping[str, Any], records: Set[str]) -> str | None:
    value = converters.to_float(stats.get("yesterday_value"))
    if value is None:
        return None
    line = f"**{name.replace('_', ' ').title()}:** {value:.2f}"
    delta_pct = converters.to_float(stats.get("pct_change_d1"))
    if delta_pct:
        direction = "up" if delta_pct > 0 else "down"
        line += f" ({direction} {abs(delta_pct):.1f}% vs hier)"
    suffix = _record_suffix(records)
    if suffix:
        line += suffix
    return line


def _format_highlight_paragraph(
    highlight: Highlight, metrics: MetricMap
) -> str | None:
    stats = metrics.get(highlight.name)
    if not stats:
        return None
    builder = _BUILDER_MAP.get(highlight.name)
    if builder is None:
        return _build_generic_line(highlight.name, stats, highlight.records)
    return builder(stats, highlight.records)


def _closing_phrase() -> str:
    try:
        phrase = phrase_picker.random_phrase(kind="motivational", mode="balanced")
    except Exception as exc:  # pragma: no cover - defensive guardrail
        domain_logging.log_message(f"Failed to pick closing phrase: {exc}", "WARN")
        phrase = "Keep the effort honest, mon ami!"
    if not phrase.endswith("!"):
        phrase += "!"
    return f"Pierre dit: {phrase}"


def _today_session_message(session_type: str | None) -> str | None:
    if not session_type:
        return None
    session = session_type.strip()
    if not session:
        return None
    if session.lower() in {"rest", "rest_day"}:
        return "Aujourd'hui c'est repos. Recharge les batteries et garde une balade legere."
    return f"Aujourd'hui: {session}. On y va fort - focus et bonne technique!"


def compose_daily_message(metrics: MetricMap, calendar_context: ContextMap | None = None) -> str:
    if not metrics:
        return "Bonjour! Pas de donnees pour hier - pense a synchroniser tes capteurs, d'accord?"

    context = calendar_context or {}
    user_name = context.get("user_name") or "mon ami"
    highlights = _select_highlights(metrics)

    lines: List[str] = []
    lines.append(f"Bonjour {user_name}! Pierre ici - pret pour ton check-in.")

    for highlight in highlights:
        paragraph = _format_highlight_paragraph(highlight, metrics)
        if paragraph:
            lines.append("")
            lines.append(paragraph)

    session_message = _today_session_message(context.get("today_session_type"))
    if session_message:
        lines.append("")
        lines.append(session_message)

    lines.append("")
    lines.append(_closing_phrase())

    return "\n".join(lines).strip()
