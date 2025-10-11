from __future__ import annotations

from typing import Iterable, List

import pytest

from pete_e.infrastructure.decorators import retry_on_network_error
from pete_e.infrastructure.wger_client import WgerError


class DummyClient:
    def __init__(self, responses: Iterable[object], max_retries: int = 3, backoff_base: float = 0.5):
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._responses = iter(responses)

    def _should_retry(self, status: int) -> bool:  # pragma: no cover - supplied via decorator
        return status in (408, 429, 500, 502, 503, 504)

    @retry_on_network_error(lambda self, status: self._should_retry(status), exception_types=(WgerError,))
    def run(self) -> object:
        result = next(self._responses)
        if isinstance(result, Exception):
            raise result
        return result


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "error") -> None:
        self.status_code = status_code
        self.text = text


def _response_with_status(status: int, text: str = "error") -> _FakeResponse:
    return _FakeResponse(status, text)


def test_retry_on_network_error_retries_retryable_status(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: List[float] = []
    monkeypatch.setattr("pete_e.infrastructure.decorators.time.sleep", lambda seconds: sleeps.append(seconds))

    responses = [
        WgerError("retry", _response_with_status(503)),
        WgerError("retry", _response_with_status(503)),
        {"ok": True},
    ]

    client = DummyClient(responses, backoff_base=0.75)

    assert client.run() == {"ok": True}
    assert sleeps == [0.75, 1.5]


def test_retry_on_network_error_stops_on_non_retryable_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pete_e.infrastructure.decorators.time.sleep", lambda _: None)

    responses = [WgerError("fatal", _response_with_status(404))]
    client = DummyClient(responses)

    with pytest.raises(WgerError):
        client.run()


def test_retry_on_network_error_handles_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: List[float] = []
    monkeypatch.setattr("pete_e.infrastructure.decorators.time.sleep", lambda seconds: sleeps.append(seconds))

    responses = [
        WgerError("network", None),
        {"ok": True},
    ]

    client = DummyClient(responses, backoff_base=0.25)

    assert client.run() == {"ok": True}
    assert sleeps == [0.25]


def test_retry_on_network_error_raises_after_exhausting_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pete_e.infrastructure.decorators.time.sleep", lambda _: None)

    responses = [WgerError("retry", _response_with_status(500))] * 4
    client = DummyClient(responses, max_retries=3)

    with pytest.raises(WgerError):
        client.run()
