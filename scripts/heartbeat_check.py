#!/usr/bin/env python3
"""Check and recover the Pete-Eebot systemd service."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess

from pete_e.infrastructure import telegram_sender
from pete_e.logging_setup import get_logger

SERVICE = os.environ.get("PETEEEBOT_SERVICE_NAME", "peteeebot.service")
SYSTEMCTL_BIN = os.environ.get("SYSTEMCTL_BIN", "/bin/systemctl")
SUDO_BIN = os.environ.get("SUDO_BIN", "sudo")
RESTART_TIMEOUT_SECONDS = float(os.environ.get("PETEEEBOT_RESTART_TIMEOUT_SECONDS", "60"))
MONITOR_LOG_PATH = Path(
    os.environ.get("PETEEEBOT_SERVICE_MONITOR_LOG", "/var/log/pete_eebot/service_monitor.log")
)

logger = get_logger("HB")


def _run(command: list[str], *, timeout: float = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _append_monitor_log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        MONITOR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MONITOR_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except OSError as exc:
        logger.warning(f"Could not write service monitor log at {MONITOR_LOG_PATH}: {exc}")


def check_service(service: str) -> bool:
    """Return whether the systemd service is active."""
    result = _run([SYSTEMCTL_BIN, "is-active", "--quiet", service])
    return result.returncode == 0


def restart_service(service: str) -> tuple[bool, str]:
    """Try to restart a systemd service without waiting for sudo prompts."""
    try:
        result = _run(
            [SUDO_BIN, "-n", SYSTEMCTL_BIN, "restart", service],
            timeout=RESTART_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"restart timed out after {RESTART_TIMEOUT_SECONDS:.0f}s"

    if result.returncode == 0:
        return True, ""

    detail = (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
    return False, detail


def send_telegram_alert(message: str) -> None:
    """Send a Telegram alert and log failures defensively."""
    try:
        telegram_sender.send_message(message)
        logger.info(f"Telegram alert sent: {message}")
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        logger.warning(f"Failed to send Telegram alert: {exc}")


def main() -> None:
    logger.info(f"Pete-Eebot heartbeat check running for {SERVICE}.")

    if check_service(SERVICE):
        logger.info(f"{SERVICE} is active.")
        return

    logger.warning(f"{SERVICE} is down; attempting restart.")
    _append_monitor_log(f"{SERVICE} was down; attempting restart.")

    restarted, detail = restart_service(SERVICE)
    if restarted:
        message = f"ALERT: {SERVICE} was down but has been restarted."
        logger.warning(message)
        _append_monitor_log(message)
        send_telegram_alert(message)
        return

    message = f"CRITICAL: {SERVICE} is down and restart failed: {detail}"
    logger.error(message)
    _append_monitor_log(message)
    send_telegram_alert(message)


if __name__ == "__main__":
    main()
