# scripts/generate_block_and_export_week1.py
from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any, Dict

from pete_e.data_access.plan_rw import create_block_and_plan, plan_week_rows
from pete_e.core.wger_exporter_v3 import export_week_to_wger


def build_week1_payload(plan_id: int) -> Dict[str, Any]:
    # This reuses your plan_week_rows function to get week 1 rows
    rows = plan_week_rows(plan_id, 1)
    # Transform into the payload shape {"days": [{day_of_week, exercises: [...]}, …]}
    days: Dict[int, list] = {}
    for r in rows:
        ex = {
            "exercise": r["exercise_id"],
            "sets": r["sets"],
            "reps": r["reps"],
            "comment": (
                f"{r['percent_1rm'] or ''}% 1RM, RIR {r['rir']}" if r["percent_1rm"] else f"RIR {r['rir']}"
            ),
        }
        days.setdefault(r["day_of_week"], []).append(ex)
    return {"days": [{"day_of_week": d, "exercises": exs} for d, exs in sorted(days.items())]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a 4-week plan and export week 1 to wger")
    parser.add_argument("--start-date", required=True, help="Monday date, e.g. 2025-09-22")
    parser.add_argument("--no-send", action="store_true", help="Skip wger export")
    args = parser.parse_args()

    start_date = dt.date.fromisoformat(args.start_date)
    plan_id, week_ids = create_block_and_plan(start_date)
    print(f"Created plan {plan_id} with weeks {week_ids}")

    payload = build_week1_payload(plan_id)
    print("Week 1 payload preview:")
    print(json.dumps(payload, indent=2))

    if not args.no_send:
        created = export_week_to_wger(payload, week_start=start_date, week_end=start_date + dt.timedelta(days=6))
        print("\nWger routine created:")
        print(json.dumps(created, indent=2))


if __name__ == "__main__":
    main()
