"""
The central orchestrator for all Pete-E business logic.

This class is responsible for coordinating the various services (narratives,
progression, validation) to generate reports and manage the training cycle.
It is completely decoupled from the data storage mechanism, relying entirely on
the DataAccessLayer (DAL) that is injected during its initialization.
"""

from datetime import date, timedelta
from typing import Optional

# Import the abstract DAL, not a concrete implementation
from pete_e.data_access.dal import DataAccessLayer
from pete_e.infra import log_utils

# Import the core logic modules that the orchestrator will coordinate
from . import narratives
from . import progression
from . import validation
from . import plan_builder


class Orchestrator:
    """Orchestrates high-level operations using the DAL."""

    def __init__(self, dal: DataAccessLayer):
        """
        Initialises the orchestrator with a data access layer.

        Args:
            dal: A concrete implementation of the DataAccessLayer abstract base class.
                 This allows the orchestrator to be storage-agnostic.
        """
        self.dal = dal
        self.current_start_date: Optional[date] = None # Manages state for the current cycle

    # --- PUBLIC REPORTING METHODS ---

    def generate_daily_report(self, target_date: date) -> str:
        """
        Generates the daily narrative by fetching the latest data via the DAL.

        Args:
            target_date: The date for which to generate the report.

        Returns:
            A string containing the daily report message.
        """
        log_utils.log_message("[Orchestrator] Generating daily report.", "INFO")
        # The orchestrator asks the DAL for data; it doesn't know how to get it.
        history = self.dal.load_history()
        if not history:
            log_utils.log_message("History is empty, cannot generate daily report.", "WARN")
            return ""

        # The core logic module (narratives) is responsible for building the text
        return narratives.build_daily_narrative(history)


    def generate_weekly_report(self, target_date: date) -> str:
        """
        Generates the weekly narrative by fetching the latest data via the DAL.

        Args:
            target_date: The date for which to generate the report.

        Returns:
            A string containing the weekly report message.
        """
        log_utils.log_message("[Orchestrator] Generating weekly report.", "INFO")
        history = self.dal.load_history()
        if not history:
            log_utils.log_message("History is empty, cannot generate weekly report.", "WARN")
            return ""

        return narratives.build_weekly_narrative(history)

    def generate_cycle_report(self, start_date: Optional[date] = None) -> str:
        """
        Plans the next 4-week training block and generates a confirmation message.

        Args:
            start_date: An optional date to override the start of the cycle.

        Returns:
            A confirmation message string.
        """
        log_utils.log_message("[Orchestrator] Generating new cycle plan.", "INFO")
        start_date = start_date or date.today()
        self.current_start_date = start_date

        block = plan_builder.build_block(self.dal, start_date)
        log_utils.log_message(
            f"New 4-week plan generated starting {start_date.isoformat()}", "INFO"
        )

        # For now, we return a simple message. Later, this could summarize the plan.
        return f"✅ New 4-week training cycle planned, starting {start_date.isoformat()}."


    # --- INTERNAL HELPER METHODS ---
    # These methods for calculating averages are now powered by the DAL.

    def _get_metric_values(self, history: dict, metric: str, days: int) -> list:
        """Extracts metric values from the last N days of history."""
        # This logic remains the same, but the `history` object it receives
        # is now guaranteed to have come from the DAL.
        last_n = list(history.values())[-days:]
        vals = []
        for day_data in last_n:
            v = None
            if metric == "rhr":
                v = day_data.get("apple", {}).get("heart_rate", {}).get("resting")
            elif metric == "sleep":
                v = day_data.get("apple", {}).get("sleep", {}).get("asleep")
            
            if v is not None:
                vals.append(v)
        return vals

    def _average(self, history: dict, metric: str, days: int) -> Optional[float]:
        """Calculates the average of a metric over the last N days."""
        vals = self._get_metric_values(history, metric, days)
        return sum(vals) / len(vals) if vals else None

    def _baseline(self, history: dict, metric: str) -> Optional[float]:
        """Calculates the 28-day baseline for a given metric."""
        return self._average(history, metric, 28)
