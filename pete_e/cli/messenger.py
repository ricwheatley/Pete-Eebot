import argparse
from pete_e.core.orchestrator import PeteE
from pete_e.core import sync


def run_sync_with_retries(max_retries: int = 3) -> bool:
    """
    Run sync with simple retry logic.
    
    Returns True if sync eventually succeeds, False otherwise.
    """
    for attempt in range(1, max_retries + 1):
        success, _ = sync.run_sync()
        if success:
            return True
        print(f"[sync] Attempt {attempt} failed, retrying...")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Pete-E orchestrator CLI")
    parser.add_argument(
        "--type",
        choices=["daily", "weekly", "cycle", "random"],
        required=True,
        help="Type of run to execute",
    )
    parser.add_argument("--start-date", type=str, help="Start date for cycle runs (YYYY-MM-DD)")
    args = parser.parse_args()

    pete = PeteE()

    if args.type == "daily":
        print("[sync] Attempting sync before daily feedback...")
        if run_sync_with_retries():
            pete.send_daily_feedback()
        else:
            print("[sync] Sync failed - aborting daily feedback.")
    elif args.type == "weekly":
        print("[sync] Attempting sync before weekly feedback...")
        if run_sync_with_retries():
            pete.send_weekly_feedback()
        else:
            print("[sync] Sync failed - aborting weekly feedback.")
    elif args.type == "cycle":
        print("[sync] Attempting sync before cycle build...")
        if run_sync_with_retries():
            pete.run_cycle(start_date=args.start_date)
        else:
            print("[sync] Sync failed - aborting cycle")
    elif args.type == "random":
        pete.send_random_message()


if __name__ == "__main__":
    main()
