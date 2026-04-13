from __future__ import annotations

import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CRON_CSV = REPO_ROOT / "pete_e" / "resources" / "pete_crontab.csv"


def _load_rows() -> list[dict[str, str]]:
    with CRON_CSV.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_core_automation_jobs_are_present_and_enabled() -> None:
    rows = _load_rows()
    jobs = {
        row["name"]: row
        for row in rows
        if row.get("name") and not row["name"].startswith("#")
    }

    assert jobs["daily sync"]["enabled"].lower() == "true"
    assert jobs["sunday review"]["enabled"].lower() == "true"
    assert jobs["weekly plan message"]["enabled"].lower() == "true"
    assert jobs["telegram listener"]["enabled"].lower() == "true"


def test_core_automation_jobs_point_to_live_entry_points() -> None:
    jobs = {row["name"]: row for row in _load_rows() if row.get("name")}

    assert "pete morning-report --send" in jobs["daily sync"]["command"]
    assert "python3 -m scripts.run_sunday_review" in jobs["sunday review"]["command"]
    assert "pete message --plan --send" in jobs["weekly plan message"]["command"]
    assert "pete telegram --listen-once" in jobs["telegram listener"]["command"]
