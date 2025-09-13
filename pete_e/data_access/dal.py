from abc import ABC, abstractmethod
from typing import Any, Dict, List
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

