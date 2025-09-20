# scripts/schedule_strength_test_week.py
#
# Create and export a one-week AMRAP test plan starting on the given Monday.
# Example:
#   python -m scripts.schedule_strength_test_week --start-date 2025-10-20

import argparse
from datetime import datetime, date

from pete_e.application.strength_test_v1 import schedule_test_week

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start-date", required=True, help="Monday date (YYYY-MM-DD) for the test week")
    args = p.parse_args()

    start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    if start.weekday() != 0:
        raise SystemExit("start-date must be a Monday")

    plan_id, week_id = schedule_test_week(start)
    print({"status": "scheduled", "plan_id": plan_id, "week_id": week_id, "start": str(start)})

if __name__ == "__main__":
    main()
