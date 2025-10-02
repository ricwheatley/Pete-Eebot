import subprocess
from pathlib import Path
from datetime import datetime

# Save in repo so it can be version-controlled
CRONTAB_FILE = Path(__file__).resolve().parent / "pete_crontab.txt"
BACKUP_DIR = Path("/home/pi") / "crontab_backups"

CRONTAB_CONTENT = """# Pete-Eebot cron schedule (local time = BST/GMT)
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin

# Reboot catch-up (sleep 2m, backfill last 3 days with retries)
@reboot cd /home/ricwheatley/pete-eebot/app && \
  set -a && . /home/ricwheatley/pete-eebot/.env && set +a && \
  /home/ricwheatley/pete-eebot/venv/bin/pete sync --days 3 --retries 3 \
    >> /var/log/pete_eebot/pete_history.log 2>&1

# Daily sync (05:40am, Mon–Fri) with retries, then send daily summary
40 5 * * 1-5 cd /home/ricwheatley/pete-eebot/app && \
  set -a && . /home/ricwheatley/pete-eebot/.env && set +a && \
  /home/ricwheatley/pete-eebot/venv/bin/pete sync --days 1 --retries 3 \
    >> /var/log/pete_eebot/pete_history.log 2>&1 && \
  /home/ricwheatley/pete-eebot/venv/bin/pete message --summary --send \
    >> /var/log/pete_eebot/pete_history.log 2>&1

# Weekly calibration + plan rollover (Sunday 16:30)
30 16 * * 0 cd /home/ricwheatley/pete-eebot/app && \
  set -a && . /home/ricwheatley/pete-eebot/.env && set +a && \
  /home/ricwheatley/pete-eebot/venv/bin/python3 -m scripts.weekly_calibration \
    >> /var/log/pete_eebot/pete_history.log 2>&1 && \
  /home/ricwheatley/pete-eebot/venv/bin/python3 -m scripts.sprint_rollover \
    >> /var/log/pete_eebot/pete_history.log 2>&1 && \
  /home/ricwheatley/pete-eebot/venv/bin/pete message --plan --send \
    >> /var/log/pete_eebot/pete_history.log 2>&1

# Telegram listener (poll once per minute, 5 updates with 25s timeout)
* * * * * cd /home/ricwheatley/pete-eebot/app && \
  set -a && . /home/ricwheatley/pete-eebot/.env && set +a && \
  /home/ricwheatley/pete-eebot/venv/bin/pete telegram --listen-once --limit 5 --timeout 25 \
    >> /var/log/pete_eebot/pete_history.log 2>&1

# Duck DNS IP refresh
*/5 * * * * curl -s "https://www.duckdns.org/update?domains=myroadmapp&token=7dc74a06-4545-4f0f-b3da-6f376dd251cf&ip="
"""

def save_crontab_file():
    """Write Pete’s crontab into the repo for versioning."""
    CRONTAB_FILE.write_text(CRONTAB_CONTENT, encoding="utf-8")
    return CRONTAB_FILE

def backup_existing_crontab():
    """Back up current crontab to ~/crontab_backups with timestamp."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_file = BACKUP_DIR / f"crontab_backup_{ts}.txt"
    with backup_file.open("w", encoding="utf-8") as f:
        subprocess.run(["crontab", "-l"], stdout=f, stderr=subprocess.DEVNULL, check=False)
    return backup_file

def activate_crontab():
    """Back up current crontab, then install the saved one."""
    backup_file = backup_existing_crontab()
    print(f"📦 Backed up existing crontab to {backup_file}")
    process = subprocess.run(
        ["crontab", str(CRONTAB_FILE)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(f"❌ Failed to activate crontab: {process.stderr.decode()}")
    return True

if __name__ == "__main__":
    path = save_crontab_file()
    print(f"✅ Crontab saved to {path}")
    if activate_crontab():
        print("✅ Crontab activated")