# pete_e/infra/telegram_sender.py

import requests
from pete_e.infra import log_utils

def send_telegram_message(token: str, chat_id: str, message: str) -> None:
    """
    Send a plain‑text message via the Telegram Bot API.

    Args:
        token: Bot API token (settings.TELEGRAM_TOKEN).
        chat_id: ID of the chat to send to (settings.TELEGRAM_CHAT_ID).
        message: The message text to send.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    try:
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        log_utils.log_message("Telegram message sent.", "INFO")
    except Exception as e:
        log_utils.log_message(f"Telegram send failed: {e}", "ERROR")
