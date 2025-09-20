# scripts/generate_block_and_export_week1.py
from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any, Dict, List

from pete_e.application.planner_v2 import build_block
from pete_e.infrastructure.plan_rw import build_week_payload
from pete_e.infrastructure.wger_exporter_v3 import export_week_to_wger


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a 4-week plan and export week 1 to wger"
    )
    parser.add_argument(
        "--start-date", required=True, help="Monday date, e.g. 2025-09-22"
    )
    parser.add_argument(
        "--no-send", action="store_true", help="Skip wger export"
    )
    args = parser.parse_args()

    start_date = dt.date.fromisoformat(args.start_date)
    plan_id, week_ids = build_block(start_date)
    print(f"Created plan {plan_id} with weeks {week_ids}")

    payload = build_week_payload(plan_id, 1)
    print("Week 1 payload preview:")
    print(json.dumps(payload, indent=2))

    if not args.no_send:
        created = export_week_to_wger(
            payload, week_start=start_date, week_end=start_date + dt.timedelta(days=6)
        )
        print("\nWger routine created or reused:")
        print(json.dumps(created, indent=2))


if __name__ == "__main__":
    main()
