# (Functional) Telegram messaging utility – sends text messages via Telegram Bot API using credentials from config.

import requests
from pete_e.config import settings
from pete_e.infrastructure import log_utils

def send_message(message: str) -> bool:
    """
    Sends a message to the configured Telegram chat.
    Reads the token and chat ID from the application settings.
    """
    # Use the settings object to get credentials
    token = settings.TELEGRAM_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        log_utils.log_message("Telegram token or chat_id not configured. Cannot send message.", "ERROR")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        log_utils.log_message("Successfully sent message to Telegram.", "INFO")
        return True
    except requests.RequestException as e:
        error_details = str(e).strip()
        if not error_details:
            error_details = e.__class__.__name__

        for sensitive_value in (token, chat_id):
            if sensitive_value:
                error_details = error_details.replace(sensitive_value, "[redacted]")

        log_utils.log_message(
            f"Failed to send message to Telegram: {error_details}",
            "ERROR",
        )
        return False
