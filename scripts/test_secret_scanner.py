"""Exercise the repository's Gitleaks policy without printing findings.

The fixture values are generated test sentinels. Scanner stdout and reports are
captured so a future regression cannot echo credential material into CI logs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".gitleaks.toml"
REQUIRED_FIXTURE_RULES = {
    "pete-duckdns-token-assignment",
    "pete-duckdns-token-url",
    "pete-withings-environment-token",
    "pete-withings-token-file",
}


def _gitleaks_binary(explicit: str | None) -> str:
    candidate = explicit or os.environ.get("GITLEAKS_BIN") or shutil.which("gitleaks")
    if not candidate:
        raise RuntimeError("Gitleaks is required; install the pinned version documented in CONTRIBUTING.md.")
    return candidate


def _scan(binary: str, target: Path, report: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            binary,
            "dir",
            "--no-banner",
            "--redact=100",
            "--config",
            str(CONFIG),
            "--report-format",
            "json",
            "--report-path",
            str(report),
            str(target),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _fixture_check(binary: str, work: Path) -> None:
    fixture = work / "fixture"
    fixture.mkdir()

    withings_access = "scanner_fixture_access_" + ("a" * 32)
    withings_refresh = "scanner_fixture_refresh_" + ("b" * 32)
    duckdns_token = "-".join(("00000000", "0000", "4000", "8000", "000000000000"))

    (fixture / ".withings_tokens.json").write_text(
        json.dumps({"access_token": withings_access, "refresh_token": withings_refresh}),
        encoding="utf-8",
    )
    (fixture / "provider.env").write_text(
        f"WITHINGS_REFRESH_TOKEN={withings_refresh}\nDUCKDNS_TOKEN={duckdns_token}\n",
        encoding="utf-8",
    )
    (fixture / "updater.txt").write_text(
        f"https://www.duckdns.org/update?domains=scanner-fixture&token={duckdns_token}&ip=\n",
        encoding="utf-8",
    )

    report = work / "fixture-report.json"
    result = _scan(binary, fixture, report)
    if result.returncode != 1 or not report.exists():
        raise RuntimeError(f"Fixture scan returned {result.returncode}; expected findings without scanner failure.")

    findings = json.loads(report.read_text(encoding="utf-8"))
    detected = {finding.get("RuleID") for finding in findings}
    missing = REQUIRED_FIXTURE_RULES - detected
    if missing:
        raise RuntimeError(f"Fixture scan missed required rule IDs: {', '.join(sorted(missing))}")


def _candidate_tree_check(binary: str, work: Path) -> None:
    tree = work / "candidate-tree"
    tree.mkdir()

    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    for raw_path in listed.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(raw_path.decode("utf-8"))
        source = ROOT / relative
        if not source.exists() or source.is_dir():
            continue
        destination = tree / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            destination.write_text(os.readlink(source), encoding="utf-8")
        else:
            shutil.copyfile(source, destination)

    result = _scan(binary, tree, work / "tree-report.json")
    if result.returncode != 0:
        raise RuntimeError(f"Candidate-tree scan returned {result.returncode}; findings are suppressed, inspect locally.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gitleaks", help="Path to the Gitleaks executable; defaults to GITLEAKS_BIN or PATH.")
    args = parser.parse_args()

    try:
        binary = _gitleaks_binary(args.gitleaks)
        with tempfile.TemporaryDirectory(prefix="pete-eebot-secret-scan-") as temp:
            work = Path(temp)
            _fixture_check(binary, work)
            _candidate_tree_check(binary, work)
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Secret-scanner verification failed: {exc}", file=sys.stderr)
        return 1

    print("Secret-scanner fixtures were detected and the candidate tree passed (finding contents suppressed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
