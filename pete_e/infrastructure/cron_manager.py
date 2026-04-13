import argparse
import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CRON_CSV = BASE_DIR.parent / "resources" / "pete_crontab.csv"
CRON_TXT = BASE_DIR / "pete_crontab.txt"
BACKUP_DIR = Path.home() / "crontab_backups"


def _is_comment_row(row: dict[str, str | None]) -> bool:
    name = (row.get("name") or "").strip()
    return not name or name.startswith("#")


def _is_enabled_row(row: dict[str, str | None]) -> bool:
    return (row.get("enabled") or "").strip().lower() == "true"


def build_crontab_from_csv():
    """Convert CSV schedule into crontab text, or None if missing."""
    if not CRON_CSV.exists():
        print(f"WARNING: Crontab CSV not found at {CRON_CSV}, skipping.")
        return None

    lines = [
        "# Pete-Eebot cron schedule (local time = BST/GMT)",
        "SHELL=/bin/bash",
        "PATH=/usr/local/bin:/usr/bin:/bin",
    ]
    with CRON_CSV.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if _is_comment_row(row) or not _is_enabled_row(row):
                continue
            lines.append(f"# {row['name']}")
            lines.append(f"{row['schedule']} {row['command']}")
    return "\n".join(lines) + "\n"


def save_crontab_file():
    text = build_crontab_from_csv()
    if not text:
        print("WARNING: No jobs to save, leaving old crontab in place.")
        return None
    CRON_TXT.write_text(text, encoding="utf-8")
    print(f"Crontab file written to {CRON_TXT}")
    return CRON_TXT


def backup_existing_crontab():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_file = BACKUP_DIR / f"crontab_backup_{ts}.txt"
    with backup_file.open("w", encoding="utf-8") as handle:
        subprocess.run(["crontab", "-l"], stdout=handle, stderr=subprocess.DEVNULL, check=False)
    return backup_file


def activate_crontab():
    if not CRON_TXT.exists():
        print("WARNING: No crontab file found, skipping activation.")
        return False
    backup_file = backup_existing_crontab()
    print(f"Backed up existing crontab to {backup_file}")
    subprocess.run(["crontab", str(CRON_TXT)], check=True)
    print("Crontab activated")
    return True


def print_summary():
    if not CRON_CSV.exists():
        print("WARNING: No crontab CSV available, nothing to summarise.")
        return
    with CRON_CSV.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = [
            [row["name"], row["schedule"], "ENABLED" if _is_enabled_row(row) else "DISABLED"]
            for row in reader
            if not _is_comment_row(row)
        ]
    if rows:
        print("\nCurrent Pete-Eebot schedule:\n")
        try:
            from tabulate import tabulate

            print(tabulate(rows, headers=["Name", "Schedule", "Status"], tablefmt="github"))
        except ModuleNotFoundError:
            headers = ["Name", "Schedule", "Status"]
            widths = [
                max(len(str(item[idx])) for item in [headers, *rows])
                for idx in range(len(headers))
            ]

            def _format_row(row):
                return " | ".join(str(value).ljust(widths[idx]) for idx, value in enumerate(row))

            print(_format_row(headers))
            print("-+-".join("-" * width for width in widths))
            for row in rows:
                print(_format_row(row))
        print()
    else:
        print("WARNING: No active jobs defined in CSV.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render and/or install the Pete-Eebot crontab.")
    parser.add_argument(
        "--print",
        dest="print_crontab",
        action="store_true",
        help="Print the generated user crontab to stdout.",
    )
    parser.add_argument("--write", action="store_true", help="Write the generated crontab file to disk.")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Install the generated crontab into the current user's crontab.",
    )
    parser.add_argument("--summary", action="store_true", help="Print a summary table of the configured jobs.")
    args = parser.parse_args(argv)

    if not any((args.print_crontab, args.write, args.activate, args.summary)):
        args.write = True
        args.activate = True
        args.summary = True

    if args.print_crontab:
        text = build_crontab_from_csv()
        if text is None:
            return 1
        sys.stdout.write(text)

    wrote_file = False
    if args.write:
        wrote_file = save_crontab_file() is not None

    if args.activate:
        if not CRON_TXT.exists() and not wrote_file:
            wrote_file = save_crontab_file() is not None
        if not wrote_file and not CRON_TXT.exists():
            return 1
        activate_crontab()

    if args.summary:
        print_summary()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
