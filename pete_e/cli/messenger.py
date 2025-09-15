"""
Unified Command-line interface for Pete-Eebot.

Supports:
- Generating reports (daily, weekly, cycle) → Telegram
- Building training plans → Postgres
- Sending validated training plans → Wger
"""

import argparse
from datetime import date

from pete_e.config import settings
from pete_e.data_access.postgres_dal import PostgresDal
from pete_e.core.orchestrator import Orchestrator
from pete_e.core.plan_builder import build_block
from pete_e.core.wger_sender import send_plan_week_to_wger
from integrations.wger.client import WgerClient
from pete_e.infra.telegram_sender import send_telegram_message
from pete_e.infra import log_utils


def main():
    parser = argparse.ArgumentParser(description="Pete-Eebot CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Reports
    report_parser = subparsers.add_parser("report", help="Generate and send reports")
    report_parser.add_argument("--type", choices=["daily", "weekly", "cycle"], required=True)
    report_parser.add_argument("--start-date", type=str, default=None)

    # Plans
    plan_parser = subparsers.add_parser("plan", help="Manage training plans")
    plan_parser.add_argument("--build", action="store_true", help="Build and save a new training plan")
    plan_parser.add_argument("--start-date", type=str, help="Start date for the plan (YYYY-MM-DD)")
    plan_parser.add_argument("--send", action="store_true", help="Send a validated plan week to Wger")
    plan_parser.add_argument("--plan-id", type=int, help="Plan ID in Postgres")
    plan_parser.add_argument("--week", type=int, help="Week number of the plan")

    args = parser.parse_args()

    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured for PostgresDal")
    dal = PostgresDal()

    if args.command == "report":
        orchestrator = Orchestrator(dal)
        message = ""

        if args.type == "daily":
            message = orchestrator.generate_daily_report(date.today())
        elif args.type == "weekly":
            message = orchestrator.generate_weekly_report(date.today())
        elif args.type == "cycle":
            start_date = date.fromisoformat(args.start_date) if args.start_date else None
            message = orchestrator.generate_cycle_report(start_date)

        if message:
            send_telegram_message(
                token=settings.TELEGRAM_TOKEN,
                chat_id=settings.TELEGRAM_CHAT_ID,
                message=message
            )
            log_utils.log_message("Report successfully sent to Telegram.", "INFO")
        else:
            log_utils.log_message("No message generated, nothing sent.", "WARN")

    elif args.command == "plan":
        if args.build:
            start_date = date.fromisoformat(args.start_date) if args.start_date else date.today()
            plan_id = build_block(dal, start_date)
            log_utils.log_message(f"Training plan {plan_id} built starting {start_date}", "INFO")

        elif args.send:
            if not args.plan_id or not args.week:
                raise RuntimeError("Must provide --plan-id and --week to send a plan week")
            client = WgerClient()
            ok = send_plan_week_to_wger(
                dal,
                plan_id=args.plan_id,
                week_number=args.week,
                current_start_date=date.fromisoformat(args.start_date) if args.start_date else date.today(),
                client=client,
            )
            if ok:
                log_utils.log_message(f"Plan {args.plan_id} week {args.week} sent to Wger", "INFO")
            else:
                log_utils.log_message(f"Failed to send plan {args.plan_id} week {args.week} to Wger", "ERROR")


if __name__ == "__main__":
    main()
