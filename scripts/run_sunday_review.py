#!/usr/bin/env python3
"""
Executes the main Sunday review, which handles weekly calibration and
cycle rollover logic.
"""
from pete_e.application.orchestrator import Orchestrator
from pete_e.infrastructure import log_utils

def main():
    """Runs the weekly end-to-end automation."""
    log_utils.info("Starting Sunday review via script...")
    try:
        orchestrator = Orchestrator()
        result = orchestrator.run_end_to_end_week()
        log_utils.info(f"Sunday review complete. Calibration: {result.calibration.message}")
        if result.rollover_triggered:
            log_utils.info(f"Cycle rollover outcome: {getattr(result.rollover, 'message', 'Completed')}")
    except Exception as e:
        log_utils.error(f"Sunday review script failed: {e}", "ERROR")
        raise

if __name__ == "__main__":
    main()