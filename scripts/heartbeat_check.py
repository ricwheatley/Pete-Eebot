#!/usr/bin/env python3
"""
Pete-Eebot Heartbeat Check

Purpose:
    - Runs every 10 minutes via cron.
    - Logs a simple heartbeat.
    - Ensures peteeebot.service is running; restarts it if not.
    - Sends a Telegram alert if a restart is needed.
"""

import datetime
import os
import sys
import subprocess

# Pete infra module for Telegram sending
from pete_e.infrastructure import telegram_sender

LOGFILE = "/var/log/pete_eebot/pete_history.log"
SERVICE = "peteeebot.service"

def log(msg: str):
    timestamp = datetime.datetime.now().isoformat()
    line = f"[{timestamp}] [HEARTBEAT] {msg}\n"
    try:
        os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        sys.stderr.write(f"Failed to write heartbeat log: {e}\n")

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
        log(f"❌ Failed to restart {service}: {e}")
        return False

def send_telegram_alert(msg: str):
    """Send an alert message via Telegram."""
    try:
        telegram_sender.send_message(msg)
        log(f"📨 Telegram alert sent: {msg}")
    except Exception as e:
        log(f"⚠️ Failed to send Telegram alert: {e}")

def main():
    log("Pete-Eebot heartbeat check running...")

    if check_service(SERVICE):
        log(f"✅ {SERVICE} is ACTIVE")
    else:
        log(f"⚠️ {SERVICE} is DOWN, attempting restart...")
        if restart_service(SERVICE):
            msg = f"⚠️ ALERT: {SERVICE} was DOWN but has been restarted 🚀"
            log(msg)
            send_telegram_alert(msg)
        else:
            msg = f"❌ CRITICAL: {SERVICE} is DOWN and restart failed"
            log(msg)
            send_telegram_alert(msg)

if __name__ == "__main__":
    main()
