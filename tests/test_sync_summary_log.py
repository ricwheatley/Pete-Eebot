from __future__ import annotations

from typing import Iterable, List, Tuple


from pete_e import logging_setup
from pete_e.application import sync


class _StubOrchestrator:
    def __init__(self, responses: Iterable[Tuple[bool, List[str], dict]]):
        self._responses = iter(responses)

    def run_daily_sync(self, days: int):  # pragma: no cover - simple stub
        return next(self._responses)


def _final_summary_line(log_path):
    lines = log_path.read_text().strip().splitlines()
    summary_lines = [line for line in lines if "Sync summary" in line]
    assert summary_lines, "Expected a sync summary line to be logged"
    return summary_lines[-1], lines, summary_lines


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

    summary_line, all_lines, summary_lines = _final_summary_line(log_path)
    assert "AppleDropbox=ok" in summary_line
    assert "Withings=ok" in summary_line
    assert "Wger=ok" in summary_line
    assert "BodyAge=ok" in summary_line
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

    summary_line, all_lines, summary_lines = _final_summary_line(log_path)
    assert summary_line == all_lines[-1]
    assert "Withings=failed" in summary_line
    assert len(summary_lines) == 1
    assert result.success is False
    assert result.failed_sources == ["Withings"]

    logging_setup.reset_logging()
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

