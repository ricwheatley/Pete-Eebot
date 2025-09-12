import argparse
from pete_e.core.orchestrator import PeteE

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly", "cycle", "random"], required=True)
    parser.add_argument("--start-date", type=str)
    args = parser.parse_args()

    pete = PeteE()

    if args.type == "daily":
        pete.send_daily_feedback()
    elif args.type == "weekly":
        pete.send_weekly_feedback()
    elif args.type == "cycle":
        pete.run_cycle(start_date=args.start_date)
    elif args.type == "random":
        pete.send_random_message()

 if __name__ == "__main__":
    main()
