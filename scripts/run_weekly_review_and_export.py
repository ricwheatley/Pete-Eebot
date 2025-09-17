# scripts/run_weekly_review_and_export.py
#
# One-shot runner for the weekly reviewer. Schedule this for Sundays 16:00.
#
# Example:
#   python -m scripts.run_weekly_review_and_export
#   python -m scripts.run_weekly_review_and_export --date 2025-09-28
#
from datetime import date, datetime
import argparse
from pete_e.core.weekly_reviewer_v2 import review_and_apply

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Override 'today' in YYYY-MM-DD for testing", default=None)
    parser.add_argument("--no-refresh", action="store_true", help="Skip MV refresh if you already did it")
    args = parser.parse_args()

    if args.date:
        today = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        today = date.today()

    res = review_and_apply(today=today, refresh_mvs=not args.no_refresh)
    print(res or {"status": "no-active-plan-or-out-of-range"})

if __name__ == "__main__":
    main()
