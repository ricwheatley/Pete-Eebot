#!/usr/bin/env python3
"""Send a Telegram message from automation without loading the full app stack."""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def find_env_path() -> Path:
    """Find the nearest .env beside this script or one of its parents."""
    script_path = Path(__file__).resolve()
    for directory in (script_path.parent, *script_path.parents):
        env_path = directory / ".env"
        if env_path.exists():
            return env_path
    raise FileNotFoundError("No .env file found beside the script or its parent directories.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Telegram notification.")
    parser.add_argument("message", type=str, help="The message content to send.")
    args = parser.parse_args()

    try:
        load_dotenv(dotenv_path=find_env_path())
    except Exception as exc:
        print(f"ERROR: Could not load environment: {exc}", file=sys.stderr)
        return 1

    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("ERROR: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set in .env.", file=sys.stderr)
        return 1

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": args.message},
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        print(f"ERROR: Telegram request failed: {exc}", file=sys.stderr)
        return 1

    response_data = response.json()
    if not response_data.get("ok"):
        description = response_data.get("description", "Unknown error")
        print(f"ERROR: Telegram rejected the message: {description}", file=sys.stderr)
        return 1

    print("Telegram notification sent successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
