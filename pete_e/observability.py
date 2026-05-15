"""Small in-process Prometheus metrics helpers for runtime observability."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import threading
from typing import Mapping


@dataclass
class _Summary:
    count: int = 0
    total: float = 0.0


_HELP: dict[str, str] = {
    "peteeebot_job_runs_total": "Total guarded runtime jobs by operation and outcome.",
    "peteeebot_job_failures_total": "Total guarded runtime job failures and timeouts.",
    "peteeebot_job_duration_seconds": "Guarded runtime job latency in seconds.",
    "peteeebot_job_retries_total": "Total job or external request retries by operation and source.",
    "peteeebot_dependency_health": "Latest dependency health result from readiness checks, 1 for healthy and 0 for unhealthy.",
    "peteeebot_dependency_latency_seconds": "Dependency readiness-check latency in seconds.",
    "peteeebot_dependency_failures_total": "Total failed dependency readiness checks.",
    "peteeebot_external_api_health": "Latest external API health result from readiness checks, 1 for healthy and 0 for unhealthy.",
    "peteeebot_external_api_latency_seconds": "External API readiness-check latency in seconds.",
    "peteeebot_external_api_failures_total": "Total failed external API readiness checks.",
    "peteeebot_alert_events_total": "Total alert events emitted or suppressed by alert type, severity, and outcome.",
    "peteeebot_alert_active": "Latest active alert state by alert type and severity, 1 for active and 0 for cleared.",
}
_TYPES: dict[str, str] = {
    "peteeebot_job_runs_total": "counter",
    "peteeebot_job_failures_total": "counter",
    "peteeebot_job_duration_seconds": "summary",
    "peteeebot_job_retries_total": "counter",
    "peteeebot_dependency_health": "gauge",
    "peteeebot_dependency_latency_seconds": "summary",
    "peteeebot_dependency_failures_total": "counter",
    "peteeebot_external_api_health": "gauge",
    "peteeebot_external_api_latency_seconds": "summary",
    "peteeebot_external_api_failures_total": "counter",
    "peteeebot_alert_events_total": "counter",
    "peteeebot_alert_active": "gauge",
}

_lock = threading.Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_summaries: dict[tuple[str, tuple[tuple[str, str], ...]], _Summary] = defaultdict(_Summary)


def reset_metrics() -> None:
    """Clear all in-process metric state. Intended for tests."""

    with _lock:
        _counters.clear()
        _gauges.clear()
        _summaries.clear()


def record_job_completed(*, operation: str, outcome: str, duration_seconds: float) -> None:
    labels = {"operation": operation, "outcome": outcome}
    with _lock:
        _inc_counter_locked("peteeebot_job_runs_total", labels)
        _observe_summary_locked("peteeebot_job_duration_seconds", max(0.0, duration_seconds), labels)
        if outcome in {"failed", "timeout"}:
            _inc_counter_locked("peteeebot_job_failures_total", labels)


def record_job_retry(*, operation: str, source: str | None = None) -> None:
    labels = {"operation": operation, "source": source or "unknown"}
    with _lock:
        _inc_counter_locked("peteeebot_job_retries_total", labels)


def record_dependency_check(
    *,
    dependency: str,
    ok: bool,
    duration_seconds: float,
    kind: str = "dependency",
) -> None:
    normalized_kind = kind or "dependency"
    dependency_labels = {"dependency": dependency, "kind": normalized_kind}
    outcome_labels = {**dependency_labels, "outcome": "ok" if ok else "failed"}
    with _lock:
        _set_gauge_locked("peteeebot_dependency_health", 1.0 if ok else 0.0, dependency_labels)
        _observe_summary_locked("peteeebot_dependency_latency_seconds", max(0.0, duration_seconds), outcome_labels)
        if not ok:
            _inc_counter_locked("peteeebot_dependency_failures_total", dependency_labels)

        if normalized_kind == "external_api":
            external_labels = {"dependency": dependency}
            external_outcome_labels = {**external_labels, "outcome": "ok" if ok else "failed"}
            _set_gauge_locked("peteeebot_external_api_health", 1.0 if ok else 0.0, external_labels)
            _observe_summary_locked(
                "peteeebot_external_api_latency_seconds",
                max(0.0, duration_seconds),
                external_outcome_labels,
            )
            if not ok:
                _inc_counter_locked("peteeebot_external_api_failures_total", external_labels)


def record_alert_event(*, alert_type: str, severity: str, outcome: str = "emitted") -> None:
    labels = {
        "alert_type": alert_type,
        "severity": severity,
        "outcome": outcome,
    }
    with _lock:
        _inc_counter_locked("peteeebot_alert_events_total", labels)


def set_alert_active(*, alert_type: str, severity: str, active: bool) -> None:
    labels = {
        "alert_type": alert_type,
        "severity": severity,
    }
    with _lock:
        _set_gauge_locked("peteeebot_alert_active", 1.0 if active else 0.0, labels)


def render_prometheus() -> str:
    """Return the current metrics in Prometheus text exposition format."""

    with _lock:
        counters = dict(_counters)
        gauges = dict(_gauges)
        summaries = {key: _Summary(value.count, value.total) for key, value in _summaries.items()}

    names = sorted(
        set(_HELP)
        | {name for name, _ in counters}
        | {name for name, _ in gauges}
        | {name for name, _ in summaries}
    )
    lines: list[str] = []
    for name in names:
        lines.append(f"# HELP {name} {_HELP.get(name, name)}")
        lines.append(f"# TYPE {name} {_TYPES.get(name, 'gauge')}")

        for (metric_name, labels), value in sorted(counters.items()):
            if metric_name == name:
                lines.append(f"{metric_name}{_format_labels(labels)} {_format_number(value)}")
        for (metric_name, labels), value in sorted(gauges.items()):
            if metric_name == name:
                lines.append(f"{metric_name}{_format_labels(labels)} {_format_number(value)}")
        for (metric_name, labels), value in sorted(summaries.items()):
            if metric_name == name:
                suffix_labels = _format_labels(labels)
                lines.append(f"{metric_name}_count{suffix_labels} {value.count}")
                lines.append(f"{metric_name}_sum{suffix_labels} {_format_number(value.total)}")

    return "\n".join(lines) + "\n"


def _inc_counter_locked(name: str, labels: Mapping[str, str], amount: float = 1.0) -> None:
    _counters[(name, _label_key(labels))] += amount


def _set_gauge_locked(name: str, value: float, labels: Mapping[str, str]) -> None:
    _gauges[(name, _label_key(labels))] = value


def _observe_summary_locked(name: str, value: float, labels: Mapping[str, str]) -> None:
    summary = _summaries[(name, _label_key(labels))]
    summary.count += 1
    summary.total += value


def _label_key(labels: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    encoded = ",".join(f'{key}="{_escape_label(value)}"' for key, value in labels)
    return f"{{{encoded}}}"


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.12g}"
