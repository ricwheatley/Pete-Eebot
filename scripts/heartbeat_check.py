#!/usr/bin/env python3
"""
Pete-Eebot Heartbeat Check

Purpose:
    - Runs every 10 minutes via cron.
    - Logs a simple heartbeat.
    - Ensures pete_eebot.service is running; restarts it if not.
    - Sends a Telegram alert if a restart is needed.
"""

import subprocess
from pete_e.infrastructure import telegram_sender
from pete_e.logging_setup import get_logger

SERVICE = "pete_eebot.service"
logger = get_logger("HB") 

def check_service(service: str) -> bool:
    """Check if a systemd service is active."""
    try:
        subprocess.run(
            ["systemctl", "is-active", "--quiet", service],
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

def restart_service(service: str) -> bool:
    """Try to restart a systemd service."""
    try:
        subprocess.run(
            ["sudo", "systemctl", "restart", service],
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to restart {service}: {e}")
        return False

def send_telegram_alert(msg: str):
    """Send an alert message via Telegram."""
    try:
        telegram_sender.send_message(msg)
        logger.info(f"📨 Telegram alert sent: {msg}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to send Telegram alert: {e}")

def main():
    logger.info("Pete-Eebot heartbeat check running...")

    if check_service(SERVICE):
        logger.info(f"✅ {SERVICE} is ACTIVE")
    else:
        logger.warning(f"⚠️ {SERVICE} is DOWN, attempting restart...")
        if restart_service(SERVICE):
            msg = f"⚠️ ALERT: {SERVICE} was DOWN but has been restarted 🚀"
            logger.warning(msg)
            send_telegram_alert(msg)
        else:
            msg = f"❌ CRITICAL: {SERVICE} is DOWN and restart failed"
            logger.error(msg)
            send_telegram_alert(msg)

if __name__ == "__main__":
    main()
