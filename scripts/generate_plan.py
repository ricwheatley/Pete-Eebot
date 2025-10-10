#!/usr/bin/env python3
"""CLI entrypoint for generating a plan and exporting it to wger."""

import argparse
import datetime as dt

from pete_e.application.plan_generation import PlanGenerationService


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a 4-week plan and export week 1 to wger",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Monday date for the plan start, e.g. 2025-10-27",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare export but do not send to wger",
    )
    args = parser.parse_args()

    start_date = dt.date.fromisoformat(args.start_date)
    PlanGenerationService().run(start_date=start_date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
