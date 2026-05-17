"""Read models for the server-rendered operator console."""

from __future__ import annotations

import json
import re
import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from pete_e.api_routes.logs_webhooks import read_recent_log_lines
from pete_e.infrastructure.cron_manager import CRON_CSV


def current_week_start(target_date: date) -> date:
    return target_date - timedelta(days=target_date.weekday())


def _error_payload(exc: Exception) -> dict[str, Any]:
    message = str(exc).strip() or exc.__class__.__name__
    return {"status": "unavailable", "error": message}


def _safe_load(loader: Callable[[], dict[str, Any]], fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = loader()
    except Exception as exc:
        payload = _error_payload(exc)
    return payload if isinstance(payload, dict) else fallback


def _source_rows(source_statuses: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, raw_status in sorted((source_statuses or {}).items()):
        status = _display_sync_source_status(raw_status)
        rows.append(
            {
                "name": str(name),
                "status": status,
                "tone": "danger" if status.lower() == "failed" else "ok",
            }
        )
    return rows


def _display_sync_source_status(raw_status: Any) -> str:
    status = str(raw_status or "unknown").strip()
    status = status.replace("\\n", "\n").splitlines()[0].strip()
    status = status.rstrip('"} ]')
    return status or "unknown"


def _metric_value(payload: dict[str, Any], key: str) -> Any:
    entry = ((payload.get("metrics") or {}).get(key) or {})
    return entry.get("value")


def _coerce_iso_date(value: Any) -> date | None:
    if hasattr(value, "isoformat") and isinstance(value, date):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            return None
    return None


def _format_date_ddmmyyyy(value: Any) -> str:
    parsed = _coerce_iso_date(value)
    return parsed.strftime("%d/%m/%Y") if parsed else str(value or "-")


def _format_day_name(value: Any) -> str:
    parsed = _coerce_iso_date(value)
    return parsed.strftime("%A") if parsed else str(value or "-")


_TEXT_LOG_RE = re.compile(r"^\[(?P<timestamp>[^\]]+)\]\s+\[(?P<level>[^\]]+)\]\s+\[(?P<tag>[^\]]+)\]\s+(?P<message>.*)$")


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _nested_log_value(payload: dict[str, Any], key: str) -> Any:
    if payload.get(key) is not None:
        return payload.get(key)
    for container_key in ("correlation", "summary"):
        container = payload.get(container_key)
        if isinstance(container, dict) and container.get(key) is not None:
            return container.get(key)
    return None


def _parse_log_row(line: str) -> dict[str, Any]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        return {
            "timestamp": _string_or_none(payload.get("timestamp")),
            "request_id": _string_or_none(_nested_log_value(payload, "request_id")),
            "job_id": _string_or_none(_nested_log_value(payload, "job_id")),
            "level": _string_or_none(payload.get("level")) or "-",
            "tag": _string_or_none(payload.get("tag")) or "-",
            "outcome": _string_or_none(_nested_log_value(payload, "outcome")),
            "message": _string_or_none(payload.get("message")) or line,
            "raw": line,
            "structured": True,
        }

    match = _TEXT_LOG_RE.match(line)
    if match:
        return {
            "timestamp": match.group("timestamp"),
            "request_id": None,
            "job_id": None,
            "level": match.group("level").strip() or "-",
            "tag": match.group("tag").strip() or "-",
            "outcome": None,
            "message": match.group("message").strip(),
            "raw": line,
            "structured": False,
        }

    return {
        "timestamp": None,
        "request_id": None,
        "job_id": None,
        "level": "-",
        "tag": "-",
        "outcome": None,
        "message": line,
        "raw": line,
        "structured": False,
    }


def _matches_filter(value: Any, expected: str | None) -> bool:
    if not expected:
        return True
    return str(value or "").strip().lower() == expected.strip().lower()


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: Any, *, decimals: int = 1) -> str:
    num = _to_float(value)
    if num is None:
        return "Missing"
    if decimals <= 0:
        return str(int(round(num)))
    return f"{num:.{decimals}f}"


def _format_minutes_for_snapshot(value: Any) -> tuple[str, str]:
    minutes = _to_float(value)
    if minutes is None:
        return "Missing", "min"
    if minutes >= 60:
        return f"{minutes / 60:.1f}", "h"
    return _format_number(minutes, decimals=0), "min"


def _metric_label(metric_key: str) -> str:
    return metric_key.replace("_", " ").strip().title()


def _build_metric_catalog(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    metric_names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if key == "date":
                continue
            if isinstance(value, (int, float)):
                metric_names.add(str(key))
    return [{"key": key, "label": _metric_label(key)} for key in sorted(metric_names)]


class WebConsoleReadModel:
    """Composes existing read services into UI-focused page payloads."""

    def __init__(
        self,
        *,
        metrics_service: Any,
        nutrition_service: Any,
        plan_service: Any,
        status_service: Any,
    ) -> None:
        self._metrics_service = metrics_service
        self._nutrition_service = nutrition_service
        self._plan_service = plan_service
        self._status_service = status_service

    def status(self, *, target_date: date, timeout: float) -> dict[str, Any]:
        health = _safe_load(
            lambda: self._health_checks(timeout),
            {"ok": False, "checks": [], "status": "unavailable"},
        )
        coach_state = _safe_load(
            lambda: self._metrics_service.coach_state(target_date.isoformat()),
            {"data_quality": {"status": "unavailable"}},
        )
        sync_outcome = _safe_load(
            lambda: self._last_sync_outcome(),
            {"status": "missing", "source_statuses": {}, "failed_sources": []},
        )
        sync_outcome["source_rows"] = _source_rows(sync_outcome.get("source_statuses"))

        return {
            "date": target_date.isoformat(),
            "health": health,
            "sync_freshness": coach_state.get("data_quality") or {},
            "last_sync": sync_outcome,
        }

    def plan(self, *, target_date: date, week_view: str = "current") -> dict[str, Any]:
        week_start = current_week_start(target_date)
        selected_view = "next" if str(week_view).strip().lower() == "next" else "current"
        if selected_view == "next":
            week_start = week_start + timedelta(days=7)
        context = _safe_load(
            lambda: self._metrics_service.plan_context(week_start.isoformat()),
            {"active_plan": None, "data_quality": "unavailable"},
        )

        active_plan = context.get("active_plan") if isinstance(context.get("active_plan"), dict) else {}
        active_plan_start = None
        if active_plan:
            raw_start = active_plan.get("start_date")
            if hasattr(raw_start, "isoformat"):
                active_plan_start = raw_start
            elif isinstance(raw_start, str):
                try:
                    active_plan_start = date.fromisoformat(raw_start)
                except ValueError:
                    active_plan_start = None

        week_plan = _safe_load(
            lambda: self._plan_service.for_week(week_start.isoformat()),
            {"columns": [], "rows": [], "status": "unavailable"},
        )

        plan_id = active_plan.get("id") if active_plan else None
        week_number = context.get("current_week_number")
        if plan_id and week_number:
            trace = _safe_load(
                lambda: self._plan_service.decision_trace(
                    plan_id=int(plan_id),
                    week_number=int(week_number),
                ),
                {"plan_id": plan_id, "week_number": week_number, "trace": [], "status": "unavailable"},
            )
        else:
            trace = {
                "plan_id": plan_id,
                "week_number": week_number,
                "trace": [],
                "status": "missing_plan",
            }

        return {
            "date": target_date.isoformat(),
            "week_start": _format_date_ddmmyyyy(week_start),
            "week_view": selected_view,
            "is_next_week_available": bool(active_plan_start and week_start < active_plan_start),
            "context": context,
            "week_plan": {
                **week_plan,
                "rows": [
                    {
                        **row,
                        "workout_date": _format_day_name(row.get("workout_date") or row.get("date")),
                    }
                    if isinstance(row, dict)
                    else row
                    for row in (week_plan.get("rows") or [])
                ],
            },
            "decision_trace": trace,
        }

    def trends(self, *, target_date: date) -> dict[str, Any]:
        coach_state = _safe_load(
            lambda: self._metrics_service.coach_state(target_date.isoformat()),
            {"summary": {}, "derived": {}, "baselines": {}, "data_quality": {"status": "unavailable"}},
        )
        daily_summary = _safe_load(
            lambda: self._metrics_service.daily_summary(target_date.isoformat()),
            {"metrics": {}, "data_quality": {"status": "unavailable"}},
        )

        baselines = coach_state.get("baselines") or {}
        derived = coach_state.get("derived") or {}
        sleep_value_display, sleep_unit_display = _format_minutes_for_snapshot(
            baselines.get("sleep_avg_7d_minutes") or _metric_value(daily_summary, "sleep_asleep_minutes")
        )
        snapshots = [
            {
                "label": "Weight",
                "value": _format_number(
                    baselines.get("weight_avg_7d_kg") or _metric_value(daily_summary, "weight_kg"),
                    decimals=1,
                ),
                "unit": "kg",
                "comparison": "7d average",
                "delta": _format_number(derived.get("weight_rate_pct_bw_per_week"), decimals=2),
                "delta_label": "% BW/week",
            },
            {
                "label": "Sleep",
                "value": sleep_value_display,
                "unit": sleep_unit_display,
                "comparison": "7d average",
                "delta": _format_number(derived.get("sleep_debt_7d_minutes"), decimals=0),
                "delta_label": "sleep debt",
            },
            {
                "label": "HRV",
                "value": _format_number(
                    baselines.get("hrv_avg_7d_ms") or _metric_value(daily_summary, "hrv_sdnn_ms"),
                    decimals=1,
                ),
                "unit": "ms",
                "comparison": "7d average",
                "delta": _format_number(derived.get("hrv_delta_vs_28d_ms"), decimals=1),
                "delta_label": "vs 28d",
            },
            {
                "label": "Volume",
                "value": _format_number(
                    derived.get("strength_load_7d_kg") or _metric_value(daily_summary, "strength_volume_kg"),
                    decimals=0,
                ),
                "unit": "kg",
                "comparison": "strength 7d",
                "delta": _format_number(derived.get("run_load_7d_km"), decimals=1),
                "delta_label": "run km 7d",
            },
        ]
        trend_rows = _safe_load(
            lambda: {
                "rows": list(
                    getattr(self._metrics_service, "_dal").get_historical_data(target_date - timedelta(days=365), target_date)
                    or []
                )
            },
            {"rows": []},
        ).get("rows", [])
        series: list[dict[str, Any]] = []
        for row in trend_rows:
            if not isinstance(row, dict):
                continue
            row_date = row.get("date")
            if not isinstance(row_date, date):
                continue
            entry: dict[str, Any] = {"date": row_date.isoformat()}
            for key, value in row.items():
                if key == "date":
                    continue
                if isinstance(value, (int, float)):
                    entry[str(key)] = value
            series.append(entry)
        series.sort(key=lambda item: str(item["date"]))

        return {
            "date": target_date.isoformat(),
            "summary": coach_state.get("summary") or {},
            "snapshots": snapshots,
            "data_quality": coach_state.get("data_quality") or daily_summary.get("data_quality") or {},
            "series": series,
            "metric_catalog": _build_metric_catalog([row for row in trend_rows if isinstance(row, dict)]),
        }

    def nutrition(self, *, target_date: date) -> dict[str, Any]:
        summary = _safe_load(
            lambda: self._nutrition_service.daily_summary(target_date.isoformat()),
            {
                "date": target_date.isoformat(),
                "meals_logged": 0,
                "source_breakdown": {},
                "confidence_breakdown": {},
                "data_quality": {"status": "unavailable"},
            },
        )
        logs = _safe_load(
            lambda: {"rows": self._nutrition_service.daily_logs(target_date.isoformat(), limit=25)},
            {"rows": []},
        ).get("rows", [])
        summary["logs"] = logs
        return summary

    def alerts(self, *, lines: int = 500, severity: str | None = None, alert_type: str | None = None) -> dict[str, Any]:
        log_view = self.logs(lines=lines, tag="ALERT", outcome=None)
        rows: list[dict[str, Any]] = []
        active_keys: set[tuple[str, str]] = set()
        for row in log_view.get("rows", []):
            raw = row.get("raw")
            if not raw:
                continue
            try:
                payload = json.loads(str(raw))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or payload.get("event") != "alert_event":
                continue
            alert = _alert_from_log_payload(payload)
            if not _matches_filter(alert.get("severity"), severity) or not _matches_filter(alert.get("type"), alert_type):
                continue
            rows.append(alert)
            if alert.get("outcome") == "emitted":
                active_keys.add((str(alert.get("type")), str(alert.get("severity"))))
        return {
            "status": log_view.get("status", "observed"),
            "filters": {"severity": severity or "", "type": alert_type or ""},
            "rows": rows,
            "active_rows": [row for row in rows if (str(row.get("type")), str(row.get("severity"))) in active_keys],
        }

    def scheduler(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        path = Path(CRON_CSV)
        try:
            with path.open(encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    name = (row.get("name") or "").strip()
                    if not name or name.startswith("#"):
                        continue
                    enabled = (row.get("enabled") or "").strip().lower() == "true"
                    command = row.get("command") or ""
                    status = "enabled" if enabled else "disabled"
                    tone = "ok" if enabled else "neutral"
                    if enabled and _cron_command_target_missing(command):
                        status = "missing target"
                        tone = "danger"
                    rows.append(
                        {
                            "name": name,
                            "schedule": row.get("schedule") or "",
                            "command": command,
                            "enabled": enabled,
                            "status": status,
                            "tone": tone,
                        }
                    )
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "rows": [], "path": str(path)}

        return {
            "status": "observed",
            "path": str(path),
            "rows": rows,
            "enabled_count": sum(1 for row in rows if row["enabled"]),
            "missing_count": sum(1 for row in rows if row["tone"] == "danger"),
        }

    def logs(self, *, lines: int, tag: str | None = None, outcome: str | None = None) -> dict[str, Any]:
        try:
            requested_lines = int(lines)
        except (TypeError, ValueError):
            requested_lines = 200
        safe_lines = max(1, min(requested_lines, 1000))
        try:
            payload = read_recent_log_lines(safe_lines)
        except HTTPException as exc:
            return {
                "status": "unavailable",
                "error": str(exc.detail),
                "path": None,
                "requested_lines": safe_lines,
                "filters": {"tag": tag or "", "outcome": outcome or ""},
                "rows": [],
                "returned_count": 0,
            }

        raw_lines = [str(line) for line in payload.get("lines", [])]
        rows = [_parse_log_row(line) for line in raw_lines]
        rows = [
            row
            for row in rows
            if _matches_filter(row.get("tag"), tag) and _matches_filter(row.get("outcome"), outcome)
        ]
        return {
            "status": "observed",
            "path": payload.get("path"),
            "requested_lines": safe_lines,
            "filters": {"tag": tag or "", "outcome": outcome or ""},
            "rows": rows,
            "returned_count": len(rows),
        }

    def _health_checks(self, timeout: float) -> dict[str, Any]:
        results = self._status_service.run_checks(timeout=timeout)
        checks = [
            {
                "name": result.name,
                "ok": bool(result.ok),
                "detail": result.detail,
                "tone": "ok" if result.ok else "danger",
            }
            for result in results
        ]
        return {"ok": all(check["ok"] for check in checks), "checks": checks}

    def _last_sync_outcome(self) -> dict[str, Any]:
        loader = getattr(self._status_service, "last_sync_outcome", None)
        if callable(loader):
            return loader()
        return {"status": "missing", "source_statuses": {}, "failed_sources": []}


def _alert_from_log_payload(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "timestamp": payload.get("timestamp"),
        "severity": payload.get("severity") or "-",
        "type": payload.get("alert_type") or "-",
        "title": payload.get("title") or payload.get("message") or "-",
        "summary": summary.get("message") or payload.get("message") or "-",
        "outcome": payload.get("outcome") or "-",
        "dedupe_key": payload.get("dedupe_key"),
        "job_id": summary.get("job_id") or payload.get("job_id"),
        "request_id": summary.get("request_id") or payload.get("request_id"),
    }


def _cron_command_target_missing(command: str) -> bool:
    module_names = re.findall(r"-m\s+([A-Za-z0-9_\.]+)", command or "")
    repo_root = Path(__file__).resolve().parents[2]
    for module_name in module_names:
        if not (repo_root / f"{module_name.replace('.', '/')}.py").exists():
            return True
    return False
