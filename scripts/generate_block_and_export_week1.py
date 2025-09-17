# scripts/generate_block_and_export_week1.py

import argparse
from datetime import date, datetime

from pete_e.core.planner_v2 import build_block
from pete_e.core.wger_exporter_v2 import export_week

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", help="Block start date (YYYY-MM-DD). If omitted, uses next Monday.", default=None)
    args = parser.parse_args()

    if args.start_date:
        start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    else:
        today = date.today()
        start = today if today.weekday() == 0 else today

    plan_id, weeks = build_block(start)
    print(f"Created plan {plan_id} with weeks {weeks}")

    # Export week 1 immediately
    result = export_week(plan_id, 1)
    print("Week 1 export:")
    print(result)

if __name__ == "__main__":
    main()
