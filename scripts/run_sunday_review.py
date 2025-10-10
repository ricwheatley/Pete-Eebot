#!/usr/bin/env python3
# scripts/run_sunday_review.py
"""Executes the main Sunday review, handling weekly calibration and cycle rollover."""
from pete_e.application.orchestrator import Orchestrator
from pete_e.infrastructure import log_utils


def main() -> None:
    """Runs the weekly end-to-end automation."""
    log_utils.info("Starting Sunday review via script...")
    orchestrator: Orchestrator | None = None
    try:
        orchestrator = Orchestrator()
        result = orchestrator.run_end_to_end_week()
        log_utils.info(f"Sunday review complete. Result: {result}")
    except Exception as exc:
        log_utils.error(f"Sunday review script failed: {exc}", exc_info=True)
        raise
    finally:
        if orchestrator is not None:
            orchestrator.close()  # Ensure DB pool is closed


if __name__ == "__main__":
    main()
