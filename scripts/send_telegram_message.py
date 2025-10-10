#!/usr/bin/env python3
"""
A simple, standalone script to send a message to a Telegram chat.

This script is designed to be called from automation, like the deploy.sh script.
It loads environment variables directly from the project's .env file,
constructs a message, and sends it using a direct HTTP request. This avoids
depending on the full application stack (Typer, DI container, etc.) for a
simple notification task, making it more robust.

Usage:
    python scripts/send_telegram_message.py "Your message here"
"""

import os
import sys
from pathlib import Path
import argparse
import requests
from dotenv import load_dotenv

def main():
    """Parses arguments, loads environment, and sends the Telegram message."""
    parser = argparse.ArgumentParser(description="Send a Telegram notification.")
    parser.add_argument("message", type=str, help="The message content to send.")
    args = parser.parse_args()

    # --- Load Environment ---
    # Dynamically find the project root and load the .env file from there.
    # This makes the script runnable from any directory.
    try:
        project_root = Path(__file__).resolve().parents[2]
        env_path = project_root / ".env"
        if not env_path.exists():
            print(f"❌ Error: .env file not found at {env_path}", file=sys.stderr)
            sys.exit(1)
        
        load_dotenv(dotenv_path=env_path)
    except Exception as e:
        print(f"❌ Error loading environment: {e}", file=sys.stderr)
        sys.exit(1)

    # --- Get Telegram Credentials ---
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("❌ Error: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set in the .env file.", file=sys.stderr)
        sys.exit(1)

    # --- Send Message ---
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": args.message,
        "parse_mode": "Markdown"  # Or "HTML" if you prefer
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        
        response_data = response.json()
        if response_data.get("ok"):
            print("✅ Telegram notification sent successfully.")
        else:
            description = response_data.get('description', 'Unknown error')
            print(f"❌ Failed to send Telegram notification: {description}", file=sys.stderr)
            sys.exit(1)
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Error sending request to Telegram: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
