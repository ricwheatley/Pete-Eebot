import argparse
from pete_e.core.orchestrator import PeteE
from pete_e.core import sync


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly", "cycle", "random"], required=True)
    parser.add_argument("--start-date", type=str)
    args = parser.parse_args()

    pete = PeteE()

    if args.type == "daily":
        print("[sync] Attempting sync before daily feedback...")
        success = sync.run_sync_with_retries()
        if success:
            pete.send_daily_feedback()
        else:
            print("[sync] Sync failed - aborting daily feedback.")
    elif args.type == "weekly":
        print("[sync] Attempting sync before weekly feedback...")
        success = sync.run_sync_with_retries()
        if success:
            pete.send_weekly_feedback()
        else:
            print("[sync] Sync failed - aborting weekly feedback.")
    elif args.type == "cycle":
        print("[sync] Attempting sync before cycle build...")
        success = sync.run_sync_with_retries()
        if success:
            pete.run_cycle(start_date=args.start_date)
        else:
            print("[sync] Sync failed - aborting cycle")
    elif args.type == "random":
        pete.send_random_message()

if __name__ == "__main__":
    main()
