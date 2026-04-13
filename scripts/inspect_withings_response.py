#!/usr/bin/env python3
"""Fetch and print the raw Withings measure payload for inspection.

Examples:
    python -m scripts.inspect_withings_response --days-back 0
    python -m scripts.inspect_withings_response --start-date 2026-04-13 --end-date 2026-04-14
    python -m scripts.inspect_withings_response --days-back 0 --latest-group-only --output withings_latest.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from pete_e.infrastructure.withings_client import WithingsClient


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date: {value}. Use YYYY-MM-DD.") from exc


def _resolve_window(
    *,
    days_back: int,
    window_days: int,
    start_date: date | None,
    end_date: date | None,
) -> tuple[datetime, datetime]:
    if (start_date is None) ^ (end_date is None):
        raise SystemExit("Provide both --start-date and --end-date together.")

    if start_date is not None and end_date is not None:
        if end_date < start_date:
            raise SystemExit("--end-date must be on or after --start-date.")
        start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
        return start_dt, end_dt

    target_day = datetime.now(timezone.utc).date() - timedelta(days=days_back)
    start_dt = datetime.combine(target_day, time.min, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=window_days)
    return start_dt, end_dt


def _fetch_payload(
    *,
    start_dt: datetime,
    end_dt: datetime,
    category: int,
    meastypes: str | None,
) -> dict[str, Any]:
    client = WithingsClient()
    client.ensure_fresh_token()

    params: dict[str, Any] = {
        "action": "getmeas",
        "category": category,
        "startdate": int(start_dt.timestamp()),
        "enddate": int(end_dt.timestamp()),
    }
    if meastypes:
        params["meastypes"] = meastypes

    response = requests.get(
        client.measure_url,
        headers={"Authorization": f"Bearer {client.access_token}"},
        params=params,
        timeout=client._request_timeout,
    )
    response.raise_for_status()
    return response.json()


def _trim_to_latest_group(payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("body")
    if not isinstance(body, dict):
        return payload

    groups = body.get("measuregrps")
    if not isinstance(groups, list) or not groups:
        return payload

    latest = max(
        groups,
        key=lambda group: (
            group.get("date", 0),
            group.get("created", 0),
        ),
    )
    trimmed = dict(payload)
    trimmed_body = dict(body)
    trimmed_body["measuregrps"] = [latest]
    trimmed["body"] = trimmed_body
    return trimmed


def _measure_type_counts(payload: dict[str, Any]) -> dict[int, int]:
    counts: dict[int, int] = {}
    body = payload.get("body")
    if not isinstance(body, dict):
        return counts

    groups = body.get("measuregrps")
    if not isinstance(groups, list):
        return counts

    for group in groups:
        if not isinstance(group, dict):
            continue
        measures = group.get("measures")
        if not isinstance(measures, list):
            continue
        for measure in measures:
            if not isinstance(measure, dict):
                continue
            raw_type = measure.get("type")
            if isinstance(raw_type, int):
                counts[raw_type] = counts.get(raw_type, 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump raw Withings measure payloads for inspection.")
    parser.add_argument("--days-back", type=int, default=0, help="Fetch a window ending today-N days back. Default: 0.")
    parser.add_argument("--window-days", type=int, default=1, help="Number of days to fetch when using --days-back. Default: 1.")
    parser.add_argument("--start-date", type=_parse_iso_date, help="Explicit UTC start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", type=_parse_iso_date, help="Explicit UTC end date inclusive (YYYY-MM-DD).")
    parser.add_argument("--category", type=int, default=1, help="Withings measure category. Default: 1.")
    parser.add_argument(
        "--meastypes",
        help="Optional comma-separated Withings measure type IDs. Omit to fetch all available measure types.",
    )
    parser.add_argument(
        "--latest-group-only",
        action="store_true",
        help="Keep only the latest measure group in the printed payload.",
    )
    parser.add_argument(
        "--show-types",
        action="store_true",
        help="Print a simple measure-type count summary before the JSON output.",
    )
    parser.add_argument("--output", type=Path, help="Optional file path to write the JSON payload.")
    args = parser.parse_args()

    start_dt, end_dt = _resolve_window(
        days_back=args.days_back,
        window_days=args.window_days,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    payload = _fetch_payload(
        start_dt=start_dt,
        end_dt=end_dt,
        category=args.category,
        meastypes=args.meastypes,
    )

    if args.latest_group_only:
        payload = _trim_to_latest_group(payload)

    if args.show_types:
        counts = _measure_type_counts(payload)
        summary = {
            "window_start_utc": start_dt.isoformat(),
            "window_end_utc": end_dt.isoformat(),
            "measure_group_count": len((payload.get("body") or {}).get("measuregrps", []) or []),
            "measure_type_counts": {str(key): counts[key] for key in sorted(counts)},
        }
        print(json.dumps(summary, indent=2, sort_keys=True))

    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote Withings payload to {args.output}")
        return 0

    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
