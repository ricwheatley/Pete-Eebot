"""
Apple Health client for Pete-E
Refactored from write_apple.py – no legacy artefacts, returns clean dicts.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from zipfile import ZipFile

from pete_e.data_access.dal import DataAccessLayer
from pete_e.infra import log_utils


def clean_num(v, as_int: bool = True):
    """Convert a value to int/float safely, or return None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if as_int else float(v)

    s = str(v).replace(",", "").strip()
    try:
        return int(float(s)) if as_int else float(s)
    except Exception:
        return None


def clean_sleep(obj):
    """Ensure sleep data is always a dict."""
    if isinstance(obj, dict):
        return obj
    return {}


def get_apple_summary(payload: dict) -> dict:
    """
    Parse Apple Health export payload into a clean dict.

    Returns:
        dict with shape:
        {
          "date": "2025-09-12",
          "steps": 10234,
          "exercise_minutes": 45,
          "calories": {"active": 300, "resting": 1600, "total": 1900},
          "stand_minutes": 600,
          "distance_m": 7200,
          "heart_rate": {"min": 55, "max": 165, "avg": 95, "resting": 60},
          "sleep": {"asleep": 420, "awake": 60, "core": 300, "deep": 90, "rem": 120, "in_bed": 480}
        }
    """
    today = payload.get("date") or date.today().isoformat()

    return {
        "date": today,
        "steps": clean_num(payload.get("steps")),
        "exercise_minutes": clean_num(payload.get("exercise_minutes")),
        "calories": {
            "active": clean_num(payload.get("calories_active")),
            "resting": clean_num(payload.get("calories_resting")),
            "total": clean_num(payload.get("calories_total")),
        },
        "stand_minutes": clean_num(payload.get("stand_minutes")),
        "distance_m": clean_num(payload.get("distance_m")),
        "heart_rate": {
            "min": clean_num(payload.get("hr_min")),
            "max": clean_num(payload.get("hr_max")),
            "avg": clean_num(payload.get("hr_avg")),
            "resting": clean_num(payload.get("hr_resting")),
        },
        "sleep": {
            "asleep": clean_num(payload.get("asleep")),
            "awake": clean_num(payload.get("awake")),
            "core": clean_num(payload.get("core")),
            "deep": clean_num(payload.get("deep")),
            "in_bed": clean_num(payload.get("in_bed")),
            "rem": clean_num(payload.get("rem")),
        },
    }


def process_apple_health_export(zip_path: str, dal: Optional[DataAccessLayer] = None) -> int:
    """Process a zipped Apple Health export and persist the contained summaries.

    Args:
        zip_path: Path to the Apple Health export zip file.
        dal: Optional data access layer. When ``None`` a :class:`PostgresDal`
            instance is created on demand.

    Returns:
        Number of daily summaries that were written to the database.
    """

    archive_path = Path(zip_path)
    if not archive_path.exists():
        raise FileNotFoundError(f"Apple Health export not found: {zip_path}")

    log_utils.log_message(
        f"Processing Apple Health export '{archive_path.name}'", "INFO"
    )

    payloads: List[Dict[str, Any]] = []
    with ZipFile(archive_path) as zf:
        json_members = [
            member
            for member in zf.infolist()
            if not member.is_dir() and member.filename.lower().endswith(".json")
        ]

        if not json_members:
            raise ValueError(
                "Apple Health export does not contain any JSON payloads to process."
            )

        for member in json_members:
            try:
                with zf.open(member) as fh:
                    raw = fh.read().decode("utf-8", errors="ignore")
                    loaded = json.loads(raw)
            except json.JSONDecodeError as exc:
                log_utils.log_message(
                    f"Skipping '{member.filename}' due to JSON decode error: {exc}",
                    "WARN",
                )
                continue

            payloads.extend(list(_iter_daily_payloads(loaded)))

    if not payloads:
        raise ValueError("No daily summaries were found in the Apple Health export.")

    processed = 0
    close_pool = None

    if dal is None:
        try:
            from pete_e.data_access.postgres_dal import PostgresDal, close_pool as closer
        except Exception as exc:  # pragma: no cover - import-time environment issues
            log_utils.log_message(
                f"Unable to initialise Postgres DAL for Apple ingestion: {exc}",
                "ERROR",
            )
            raise

        dal = PostgresDal()
        close_pool = closer

    try:
        for payload in payloads:
            normalised = _normalise_daily_payload(payload)
            if not normalised:
                continue

            day, metrics = normalised
            dal.save_apple_daily(day, metrics)
            processed += 1
            log_utils.log_message(
                f"Saved Apple Health summary for {day.isoformat()}", "INFO"
            )
    finally:
        if close_pool:
            close_pool()

    log_utils.log_message(
        f"Processed {processed} Apple Health daily summaries from export.", "INFO"
    )

    return processed


def _iter_daily_payloads(obj: Any) -> Iterator[Dict[str, Any]]:
    """Yield candidate daily summary payloads from an arbitrary structure."""

    if isinstance(obj, dict):
        if any(key in obj for key in ("date", "day", "day_date")):
            yield obj

        for key in ("days", "entries", "data", "summaries"):
            value = obj.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        yield from _iter_daily_payloads(item)
        return

    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                yield from _iter_daily_payloads(item)


def _parse_date(value: str) -> Optional[date]:
    if not value:
        return None

    cleaned = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(cleaned[: len(fmt)], fmt).date()
        except ValueError:
            continue

    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        return None


def _get_first(container: Dict[str, Any], *paths: Iterable[str]) -> Any:
    for path in paths:
        if isinstance(path, str):
            value = container.get(path)
        else:
            value = container
            for key in path:
                if not isinstance(value, dict):
                    value = None
                    break
                value = value.get(key)
        if value is not None:
            return value
    return None


def _normalise_daily_payload(payload: Dict[str, Any]) -> Optional[Tuple[date, Dict[str, Any]]]:
    day_value = (
        payload.get("date")
        or payload.get("day")
        or payload.get("day_date")
        or payload.get("summary_date")
    )
    day = _parse_date(day_value) if day_value else None

    if not day:
        log_utils.log_message(
            "Skipping Apple payload with missing/invalid date field.", "WARN"
        )
        return None

    # Handle nested calorie structures
    calories_block = payload.get("calories")
    if isinstance(calories_block, dict):
        for key, alias in (
            ("active", "calories_active"),
            ("resting", "calories_resting"),
            ("total", "calories_total"),
        ):
            if alias not in payload and key in calories_block:
                payload[alias] = calories_block.get(key)

    heart_block = payload.get("heart_rate")
    if isinstance(heart_block, dict):
        for key, alias in (
            ("min", "hr_min"),
            ("max", "hr_max"),
            ("avg", "hr_avg"),
            ("resting", "hr_resting"),
        ):
            if alias not in payload and key in heart_block:
                payload[alias] = heart_block.get(key)

    sleep_block: Dict[str, Any] = {}
    for candidate in (payload.get("sleep_minutes"), payload.get("sleep")):
        if isinstance(candidate, dict):
            if "minutes" in candidate and isinstance(candidate["minutes"], dict):
                sleep_block = candidate["minutes"]
            else:
                sleep_block = candidate
            break

    def sleep_val(*keys: Iterable[str]) -> Optional[int]:
        value = _get_first(sleep_block, *keys)
        return clean_num(value) if value is not None else None

    distance_m = clean_num(
        _get_first(
            payload,
            "distance_m",
            ("distance", "meters"),
            ("distance", "m"),
        )
    )
    if distance_m is None:
        distance_km = clean_num(
            _get_first(payload, "distance_km", ("distance", "km")),
            as_int=False,
        )
        if distance_km is not None:
            distance_m = int(distance_km * 1000)

    metrics = {
        "steps": clean_num(_get_first(payload, "steps", ("activity", "steps"))),
        "exercise_minutes": clean_num(
            _get_first(payload, "exercise_minutes", ("activity", "exercise_minutes"))
        ),
        "calories_active": clean_num(payload.get("calories_active")),
        "calories_resting": clean_num(payload.get("calories_resting")),
        "calories_total": clean_num(payload.get("calories_total")),
        "stand_minutes": clean_num(payload.get("stand_minutes")),
        "distance_m": distance_m,
        "hr_resting": clean_num(payload.get("hr_resting")),
        "hr_avg": clean_num(payload.get("hr_avg")),
        "hr_max": clean_num(payload.get("hr_max")),
        "hr_min": clean_num(payload.get("hr_min")),
        "sleep_total_minutes": sleep_val("in_bed", "total", "total_minutes"),
        "sleep_asleep_minutes": sleep_val("asleep", "asleep_minutes"),
        "sleep_rem_minutes": sleep_val("rem", "rem_minutes"),
        "sleep_deep_minutes": sleep_val("deep", "deep_minutes"),
        "sleep_core_minutes": sleep_val("core", "core_minutes", "light"),
        "sleep_awake_minutes": sleep_val("awake", "awake_minutes"),
    }

    # Derive total sleep if not provided but asleep and awake are available.
    if metrics["sleep_total_minutes"] is None:
        asleep = metrics["sleep_asleep_minutes"]
        awake = metrics["sleep_awake_minutes"]
        if asleep is not None and awake is not None:
            metrics["sleep_total_minutes"] = asleep + awake
        elif asleep is not None:
            metrics["sleep_total_minutes"] = asleep

    return day, metrics
