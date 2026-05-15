"""Process-local guard for high-risk operator workflows."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import threading
from typing import Callable, Iterator, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class OperationInProgress(RuntimeError):
    """Raised when a guarded operation is already running."""

    requested_operation: str
    active_operation: str | None

    def __str__(self) -> str:
        active = self.active_operation or "another high-risk operation"
        return f"Cannot start {self.requested_operation}; {active} is already running."


class HighRiskOperationGuard:
    """Serializes sync/plan/deploy-sensitive operations in this process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_operation: str | None = None

    @property
    def active_operation(self) -> str | None:
        with self._state_lock:
            return self._active_operation

    def acquire(self, operation: str) -> None:
        if not self._lock.acquire(blocking=False):
            raise OperationInProgress(
                requested_operation=operation,
                active_operation=self.active_operation,
            )
        with self._state_lock:
            self._active_operation = operation

    def release(self) -> None:
        with self._state_lock:
            self._active_operation = None
        self._lock.release()

    @contextmanager
    def hold(self, operation: str) -> Iterator[None]:
        self.acquire(operation)
        try:
            yield
        finally:
            self.release()

    def run(self, operation: str, callback: Callable[[], T]) -> T:
        with self.hold(operation):
            return callback()


high_risk_operation_guard = HighRiskOperationGuard()
