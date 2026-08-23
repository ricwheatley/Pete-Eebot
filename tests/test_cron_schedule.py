from __future__ import annotations

import csv
from pathlib import Path
import re

from pete_e.infrastructure import cron_manager
from pete_e.infrastructure.cron_manager import CRON_CSV, build_crontab_from_csv


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_rows() -> list[dict[str, str]]:
    with CRON_CSV.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
    """Perform load rows."""


def test_cron_source_is_a_bundled_resource() -> None:
    assert CRON_CSV.is_file()
    assert CRON_CSV.name == "pete_crontab.csv"


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
    assert jobs["weekly plan message"]["schedule"] == "30 20 * * 0"
    assert jobs["telegram listener"]["enabled"].lower() == "true"
    assert jobs["heartbeat check"]["enabled"].lower() == "true"
    assert jobs["heartbeat check"]["schedule"] == "*/5 * * * *"
    assert "monitor services" not in jobs
    """Perform test core automation jobs are present and enabled."""


def test_core_automation_jobs_point_to_live_entry_points() -> None:
    jobs = {row["name"]: row for row in _load_rows() if row.get("name")}

    assert "pete morning-report --send" in jobs["daily sync"]["command"]
    assert "python3 -m scripts.run_sunday_review" in jobs["sunday review"]["command"]
    assert "pete message --plan --send" in jobs["weekly plan message"]["command"]
    assert "pete telegram --listen-once" in jobs["telegram listener"]["command"]
    """Perform test core automation jobs point to live entry points."""


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
    """Perform test enabled python module jobs point to existing scripts."""


def test_rendered_crontab_includes_core_jobs_and_omits_disabled_entries() -> None:
    crontab = build_crontab_from_csv()

    assert crontab is not None
    assert "python3 -m scripts.run_sunday_review" in crontab
    assert "pete message --plan --send" in crontab
    assert "pete telegram --listen-once" in crontab
    assert "scripts.log_rotate" not in crontab
    assert "scripts.check_for_updates" not in crontab
    """Perform test rendered crontab includes core jobs and omits disabled entries."""


def test_generated_crontab_is_written_to_an_external_target(
    monkeypatch, tmp_path: Path
) -> None:
    output = tmp_path / "state" / "pete_crontab.txt"
    monkeypatch.setattr(cron_manager, "CRON_TXT", output)

    assert cron_manager.save_crontab_file() == output
    assert output.is_file()
    assert "pete morning-report --send" in output.read_text(encoding="utf-8")
