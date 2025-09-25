"""Utility helpers for loading aggregated metrics for narratives."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Mapping

from pete_e.domain.data_access import DataAccessLayer
from pete_e.infrastructure import log_utils


def _coerce_numeric(value: Any) -> Any:
    """Convert Decimal instances to float for easier downstream formatting."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def get_metrics_overview(dal: DataAccessLayer) -> Dict[str, Dict[str, Any]]:
    """Return metrics_overview rows keyed by metric name."""
    try:
        rows = dal.get_metrics_overview()
    except Exception as exc:
        log_utils.log_message(f"Failed to load metrics_overview: {exc}", "ERROR")
        return {}

    metrics: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        name = row.get("metric_name")
        if not name:
            continue
        metrics[str(name)] = {
            key: _coerce_numeric(value)
            for key, value in row.items()
            if key != "metric_name"
        }
    return metrics
