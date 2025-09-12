"""Thin wrapper around Telegram Bot API."""
Import os
Import requests

def send_message(msg: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg},
        timeout=20,
    )
    if not r.ok:
        print(f"[telegram] Error {r.status_code}: {r.text[:200]}")
    else:
        print("[] Telegram] Message sent.")
