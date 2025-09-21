from __future__ import annotations

from typing import Iterable, List, Tuple

from pete_e import logging_setup
from pete_e.application import sync


class _StubOrchestrator:
    def __init__(self, responses: Iterable[Tuple[bool, List[str], dict]]):
        self._responses = iter(responses)

    def run_daily_sync(self, days: int):  # pragma: no cover - simple stub
        return next(self._responses)


def _final_summary_bundle(log_path):
    lines = log_path.read_text().strip().splitlines()
    summary_indices = [idx for idx, line in enumerate(lines) if "Sync summary" in line]
    assert summary_indices, "Expected a sync summary line to be logged"
    final_idx = summary_indices[-1]
    summary_line = lines[final_idx]

    trailing_lines: List[str] = []
    cursor = final_idx + 1
    while cursor < len(lines) and "Sync summary" not in lines[cursor]:
        trailing_lines.append(lines[cursor])
        cursor += 1

    summary_lines = [lines[i] for i in summary_indices]
    return summary_line, trailing_lines, lines, summary_lines


def test_run_sync_logs_single_summary_line_success(tmp_path, monkeypatch):
    log_path = tmp_path / "pete_history.log"
    logger = logging_setup.configure_logging(log_path=log_path, force=True)
    monkeypatch.setattr(
        sync,
        "Orchestrator",
        lambda: _StubOrchestrator(
            [
                (
                    True,
                    [],
                    {
                        "AppleDropbox": "ok",
                        "Withings": "ok",
                        "Wger": "ok",
                        "BodyAge": "ok",
                    },
                )
            ]
        ),
    )

    result = sync.run_sync_with_retries(days=1, retries=1)
    for handler in logger.handlers:
        if hasattr(handler, "flush"):
            handler.flush()

    summary_line, trailing_lines, all_lines, summary_lines = _final_summary_bundle(log_path)
    assert "AppleDropbox=ok" in summary_line
    assert "Withings=ok" in summary_line
    assert "Wger=ok" in summary_line
    assert "BodyAge=ok" in summary_line
    assert trailing_lines == []
    assert summary_line == all_lines[-1]
    assert len(summary_lines) == 1
    assert result.success is True
    assert result.failed_sources == []

    logging_setup.reset_logging()
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def test_run_sync_logs_failure_summary_once(tmp_path, monkeypatch):
    log_path = tmp_path / "pete_history.log"
    logger = logging_setup.configure_logging(log_path=log_path, force=True)
    monkeypatch.setattr(
        sync,
        "Orchestrator",
        lambda: _StubOrchestrator(
            [
                (
                    False,
                    ["Withings"],
                    {
                        "AppleDropbox": "ok",
                        "Withings": "failed",
                        "Wger": "ok",
                        "BodyAge": "ok",
                    },
                )
            ]
        ),
    )

    result = sync.run_sync_with_retries(days=1, retries=1)
    for handler in logger.handlers:
        if hasattr(handler, "flush"):
            handler.flush()

    summary_line, trailing_lines, all_lines, summary_lines = _final_summary_bundle(log_path)
    assert summary_line == summary_lines[-1]
    assert "Withings=failed" in summary_line
    assert trailing_lines == ["Withings data unavailable today"]
    assert trailing_lines[-1] == all_lines[-1]
    assert len(summary_lines) == 1
    assert result.success is False
    assert result.failed_sources == ["Withings"]

    logging_setup.reset_logging()
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

