#!/usr/bin/env python3
"""
Pete-Eebot Heartbeat Check

Purpose:
    - Ensures the Pi and Pete-Eebot stack are alive.
    - Logs a simple heartbeat message to pete_history.log.
    - Can be expanded later to include deeper health checks (DB, API, services).
"""

import datetime
import os
import sys

LOGFILE = "/var/log/pete_eebot/pete_history.log"

def log(msg: str):
    timestamp = datetime.datetime.now().isoformat()
    line = f"[{timestamp}] [HEARTBEAT] {msg}\n"
    try:
        os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        sys.stderr.write(f"Failed to write heartbeat log: {e}\n")

def main():
    log("Pete-Eebot heartbeat check passed ✅")

if __name__ == "__main__":
    main()
