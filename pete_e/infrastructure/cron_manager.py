import csv
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
CRON_CSV = BASE_DIR.parent / "resources" / "pete_crontab.csv"
CRON_TXT = BASE_DIR / "pete_crontab.txt"
BACKUP_DIR = Path.home() / "crontab_backups"

def build_crontab_from_csv():
    """Convert CSV schedule into crontab text, or None if missing."""
    if not CRON_CSV.exists():
        print(f"⚠️ WARNING: Crontab CSV not found at {CRON_CSV}, skipping.")
        return None

    lines = [
        "# Pete-Eebot cron schedule (local time = BST/GMT)",
        "SHELL=/bin/bash",
        "PATH=/usr/local/bin:/usr/bin:/bin",
    ]
    with CRON_CSV.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["name"].startswith("#"):  # skip comments
                continue
            if row.get("enabled", "").lower() != "true":
                continue
            lines.append(f"# {row['name']}")
            lines.append(f"{row['schedule']} {row['command']}")
    return "\n".join(lines) + "\n"

def save_crontab_file():
    text = build_crontab_from_csv()
    if not text:
        print("⚠️ No jobs to save, leaving old crontab in place.")
        return None
    CRON_TXT.write_text(text, encoding="utf-8")
    print(f"✅ Crontab file written to {CRON_TXT}")
    return CRON_TXT

def backup_existing_crontab():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_file = BACKUP_DIR / f"crontab_backup_{ts}.txt"
    with backup_file.open("w", encoding="utf-8") as f:
        subprocess.run(["crontab", "-l"], stdout=f, stderr=subprocess.DEVNULL, check=False)
    return backup_file

def activate_crontab():
    if not CRON_TXT.exists():
        print("⚠️ No crontab file found, skipping activation.")
        return False
    backup_file = backup_existing_crontab()
    print(f"📦 Backed up existing crontab to {backup_file}")
    subprocess.run(["crontab", str(CRON_TXT)], check=True)
    print("✅ Crontab activated")
    return True

def print_summary():
    if not CRON_CSV.exists():
        print("⚠️ No crontab CSV available, nothing to summarise.")
        return
    with CRON_CSV.open() as f:
        reader = csv.DictReader(f)
        rows = [
            [row["name"], row["schedule"], "ENABLED" if row["enabled"].lower() == "true" else "DISABLED"]
            for row in reader if not row["name"].startswith("#")
        ]
    if rows:
        from tabulate import tabulate
        print("\n📋 Current Pete-Eebot schedule:\n")
        print(tabulate(rows, headers=["Name", "Schedule", "Status"], tablefmt="github"))
        print()
    else:
        print("⚠️ No active jobs defined in CSV.")

if __name__ == "__main__":
    save_crontab_file()
    activate_crontab()
    print_summary()
