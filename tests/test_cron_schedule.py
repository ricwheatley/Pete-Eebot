from __future__ import annotations

import csv
from pathlib import Path
import re

from pete_e.infrastructure.cron_manager import build_crontab_from_csv


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


def test_enabled_python_module_jobs_point_to_existing_scripts() -> None:
    rows = _load_rows()
    for row in rows:
        if (row.get("enabled") or "").lower() != "true":
            continue
        command = row.get("command", "")
        module_names = re.findall(r"-m\s+([A-Za-z0-9_\.]+)", command)
        for module_name in module_names:
            module_path = REPO_ROOT / f"{module_name.replace('.', '/')}.py"
            assert module_path.exists(), f"{row['name']} targets missing module {module_name}"


def test_rendered_crontab_includes_core_jobs_and_omits_disabled_entries() -> None:
    crontab = build_crontab_from_csv()

    assert crontab is not None
    assert "python3 -m scripts.run_sunday_review" in crontab
    assert "pete message --plan --send" in crontab
    assert "pete telegram --listen-once" in crontab
    assert "scripts.log_rotate" not in crontab
    assert "scripts.check_for_updates" not in crontab
