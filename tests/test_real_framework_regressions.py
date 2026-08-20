from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_normal_workflow_regressions_use_real_frameworks() -> None:
    script = Path(__file__).with_name("real_framework_regressions.py")
    completed = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["plan_http_job"] == {
        "api_default_terminal": "succeeded",
        "api_explicit_terminal": "succeeded",
        "serialized_weeks": [4, 4, 4],
        "web_default_terminal": "succeeded",
    }
    assert payload["cli"] == {"default_weeks": 4, "invalid_exit_code": 2}
    assert payload["sync_retry"] == {
        "exception_exhausted_attempts": 3,
        "exception_job_terminal": "failed",
        "final_error_logs": 1,
        "final_job_logs": 1,
        "final_job_metrics": 1,
        "immediate_attempts": 1,
        "recovered_attempts": 2,
        "structured_exhausted_attempts": 3,
    }
