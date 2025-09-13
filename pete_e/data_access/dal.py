from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from datetime import date


class DataAccessLayer(ABC):
    """
    Abstract Base Class for a Data Access Layer.
    Defines the contract for all data storage operations, ensuring that
    the business logic can interact with any storage backend (JSON, DB, etc.)
    through a consistent interface.
    """

    @abstractmethod
    def load_lift_log(self) -> Dict[str, Any]:
        """Loads the entire lift log."""
        pass

    @abstractmethod
    def save_lift_log(self, log: Dict[str, Any]) -> None:
        """Saves the entire lift log."""
        pass

    @abstractmethod
    def load_history(self) -> Dict[str, Any]:
        """Loads the consolidated history file."""
        pass

    @abstractmethod
    def save_history(self, history: Dict[str, Any]) -> None:
        """Saves the consolidated history file."""
        pass

    @abstractmethod
    def save_daily_summary(self, summary: Dict[str, Any], day: date) -> None:
        """Saves a single day's consolidated summary."""
        pass
        
    @abstractmethod
    def load_body_age(self) -> Dict[str, Any]:
        """Loads the body age data file."""
        pass

    @abstractmethod
    def get_historical_metrics(self, days: int) -> List[Dict[str, Any]]:
        """Retrieves the last N days of historical metrics."""
        pass

    @abstractmethod
    def get_daily_summary(self, target_date: date) -> Optional[Dict[str, Any]]:
        """
        Retrieves a consolidated summary for a specific day.

        Args:
            target_date: The date for which to retrieve the summary.

        Returns:
            A dictionary containing the day's data, or None if not found.
        """
        pass

    @abstractmethod
    def get_historical_data(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """
        Retrieves a range of historical daily summaries.

        Args:
            start_date: The starting date of the range.
            end_date: The ending date of the range.

        Returns:
            A list of daily summary dictionaries.
        """
        pass
