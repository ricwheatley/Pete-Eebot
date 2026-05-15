"""Read models for the server-rendered operator console."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable


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
        status = str(raw_status or "unknown")
        rows.append(
            {
                "name": str(name),
                "status": status,
                "tone": "danger" if status.lower() == "failed" else "ok",
            }
        )
    return rows


def _metric_value(payload: dict[str, Any], key: str) -> Any:
    entry = ((payload.get("metrics") or {}).get(key) or {})
    return entry.get("value")


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

    def plan(self, *, target_date: date) -> dict[str, Any]:
        week_start = current_week_start(target_date)
        context = _safe_load(
            lambda: self._metrics_service.plan_context(target_date.isoformat()),
            {"active_plan": None, "data_quality": "unavailable"},
        )
        week_plan = _safe_load(
            lambda: self._plan_service.for_week(week_start.isoformat()),
            {"columns": [], "rows": [], "status": "unavailable"},
        )

        active_plan = context.get("active_plan") if isinstance(context.get("active_plan"), dict) else {}
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
            "week_start": week_start.isoformat(),
            "context": context,
            "week_plan": week_plan,
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
        snapshots = [
            {
                "label": "Weight",
                "value": baselines.get("weight_avg_7d_kg") or _metric_value(daily_summary, "weight_kg"),
                "unit": "kg",
                "comparison": "7d average",
                "delta": derived.get("weight_rate_pct_bw_per_week"),
                "delta_label": "% BW/week",
            },
            {
                "label": "Sleep",
                "value": baselines.get("sleep_avg_7d_minutes") or _metric_value(daily_summary, "sleep_asleep_minutes"),
                "unit": "min",
                "comparison": "7d average",
                "delta": derived.get("sleep_debt_7d_minutes"),
                "delta_label": "sleep debt",
            },
            {
                "label": "HRV",
                "value": baselines.get("hrv_avg_7d_ms") or _metric_value(daily_summary, "hrv_sdnn_ms"),
                "unit": "ms",
                "comparison": "7d average",
                "delta": derived.get("hrv_delta_vs_28d_ms"),
                "delta_label": "vs 28d",
            },
            {
                "label": "Volume",
                "value": derived.get("strength_load_7d_kg") or _metric_value(daily_summary, "strength_volume_kg"),
                "unit": "kg",
                "comparison": "strength 7d",
                "delta": derived.get("run_load_7d_km"),
                "delta_label": "run km 7d",
            },
        ]

        return {
            "date": target_date.isoformat(),
            "summary": coach_state.get("summary") or {},
            "snapshots": snapshots,
            "data_quality": coach_state.get("data_quality") or daily_summary.get("data_quality") or {},
        }

    def nutrition(self, *, target_date: date) -> dict[str, Any]:
        return _safe_load(
            lambda: self._nutrition_service.daily_summary(target_date.isoformat()),
            {
                "date": target_date.isoformat(),
                "meals_logged": 0,
                "source_breakdown": {},
                "confidence_breakdown": {},
                "data_quality": {"status": "unavailable"},
            },
        )

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
