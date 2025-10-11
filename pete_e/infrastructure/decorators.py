"""Infrastructure-level decorators used across API clients."""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Iterable, Optional, Tuple, Type, TypeVar

from pete_e.infrastructure import log_utils

TFunc = TypeVar("TFunc", bound=Callable[..., Any])


def retry_on_network_error(
    should_retry: Callable[[Any, int], bool],
    *,
    exception_types: Iterable[Type[BaseException]] = (),
) -> Callable[[TFunc], TFunc]:
    """Retry decorator with exponential backoff for transient failures.

    Parameters
    ----------
    should_retry:
        Callable that accepts ``self`` and an HTTP status code, returning ``True``
        when the request should be retried.
    exception_types:
        Iterable of exception types that should be intercepted by the decorator.
        This is typically a tuple containing an API-specific error (e.g.
        :class:`~pete_e.infrastructure.wger_client.WgerError`).
    """

    exception_tuple: Tuple[Type[BaseException], ...] = tuple(exception_types)

    def decorator(func: TFunc) -> TFunc:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            max_retries: int = getattr(self, "max_retries", 1)
            backoff_base: float = getattr(self, "backoff_base", 0.0)

            last_exc: Optional[BaseException] = None

            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except exception_tuple as exc:  # type: ignore[misc]
                    last_exc = exc
                    status_code: Optional[int] = getattr(exc, "status_code", None)

                    # Determine whether this exception qualifies for a retry.
                    retry_allowed = True
                    if status_code is not None:
                        retry_allowed = should_retry(self, status_code)

                    if not retry_allowed or attempt == max_retries - 1:
                        raise

                    method = _extract_arg("method", 0, args, kwargs)
                    path = _extract_arg("path", 1, args, kwargs)
                    sleep_for = backoff_base * (2 ** attempt)

                    if status_code is None:
                        log_utils.warn(
                            f"[retry] network error on {method} {path}: {exc!r}, "
                            f"retrying in {sleep_for:.2f}s..."
                        )
                    else:
                        log_utils.warn(
                            f"[retry] transient {status_code} on {method} {path}, "
                            f"retrying in {sleep_for:.2f}s..."
                        )

                    if sleep_for > 0:
                        time.sleep(sleep_for)

            if last_exc is not None:
                raise last_exc

            raise RuntimeError("retry_on_network_error failed without executing the function.")

        return wrapper  # type: ignore[return-value]

    return decorator


def _extract_arg(name: str, position: int, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Helper to extract positional/keyword arguments for logging."""

    if position < len(args):
        return args[position]
    if name in kwargs:
        return kwargs[name]
    return "<unknown>"

