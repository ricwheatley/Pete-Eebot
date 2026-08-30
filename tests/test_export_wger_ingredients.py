from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import export_wger_ingredients as exporter


_GENERATED_AUTH_HEADER = "Token " + "-".join(("s01", "generated", "api", "key"))


class _Response:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def test_export_rejects_cross_origin_before_reusing_authorization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Characterize the exporter's credential-bearing pagination boundary."""

    class FakeSession:
        calls = 0

        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, **kwargs: object) -> _Response:
            type(self).calls += 1
            if self.calls == 1:
                return _Response(
                    {
                        "count": 1,
                        "results": [{"id": 1}],
                        "next": "https://pagination.invalid/collect",
                    }
                )
            assert url.startswith("https://pagination.invalid/")
            assert "Authorization" in kwargs["headers"]  # type: ignore[operator]
            return _Response({"count": 1, "results": [], "next": None})

    monkeypatch.setattr(exporter.requests, "Session", FakeSession)

    with pytest.raises(
        RuntimeError, match="Rejected Wger URL outside the configured origin"
    ):
        exporter.export_ingredients(
            base_url="https://wger.de/api/v2",
            language=2,
            limit=10_000,
            offset=0,
            output=tmp_path / "ingredients.json",
            auth_header=_GENERATED_AUTH_HEADER,
            timeout=5.0,
            retries=0,
            max_pages=None,
        )

    assert FakeSession.calls == 1


def _run_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session: object,
    *,
    max_pages: int | None = None,
) -> tuple[int, Path]:
    monkeypatch.setattr(exporter.requests, "Session", lambda: session)
    output = tmp_path / "ingredients.json"
    total = exporter.export_ingredients(
        base_url="https://fitness.example/wger/api/v2",
        language=2,
        limit=2,
        offset=0,
        output=output,
        auth_header=_GENERATED_AUTH_HEADER,
        timeout=5.0,
        retries=0,
        max_pages=max_pages,
    )
    return total, output


class _SequenceSession:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __enter__(self) -> _SequenceSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        return self.responses[len(self.calls) - 1]


def test_export_streams_same_origin_pages_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = _SequenceSession(
        [
            _Response(
                {
                    "count": 4,
                    "results": [{"id": 1}, {"id": 1}],
                    "next": "?limit=2&offset=2",
                }
            ),
            _Response(
                {
                    "count": 4,
                    "results": [{"id": 2}],
                    "next": "https://FITNESS.EXAMPLE:443/wger/api/v2/ingredientinfo/?limit=2&offset=4",
                }
            ),
            _Response({"count": 4, "results": [{"id": 3}], "next": None}),
        ]
    )

    total, output = _run_export(monkeypatch, tmp_path, session)

    assert total == 4
    assert json.loads(output.read_text(encoding="utf-8")) == [
        {"id": 1},
        {"id": 1},
        {"id": 2},
        {"id": 3},
    ]
    assert [call[0] for call in session.calls] == [
        "https://fitness.example/wger/api/v2/ingredientinfo/",
        "https://fitness.example/wger/api/v2/ingredientinfo/?limit=2&offset=2",
        "https://fitness.example/wger/api/v2/ingredientinfo/?limit=2&offset=4",
    ]
    assert session.calls[0][1]["params"] == {
        "language": 2,
        "limit": 2,
        "offset": 0,
        "ordering": "id",
    }
    assert all(call[1]["allow_redirects"] is False for call in session.calls)
    assert all("Authorization" in call[1]["headers"] for call in session.calls)  # type: ignore[operator]
    assert [call[1]["params"] for call in session.calls[1:]] == [None, None]


@pytest.mark.parametrize(
    ("next_value", "message"),
    [
        (
            "https://pagination.invalid/collect",
            "Rejected Wger URL outside the configured origin.",
        ),
        (
            "https://user:password@fitness.example/wger/api/v2/collect",
            "Wger pagination returned an invalid next URL.",
        ),
        (
            "https://fitness.example/wger/api/v2/collect#fragment",
            "Wger pagination returned an invalid next URL.",
        ),
        (1, "Wger pagination returned an invalid next URL."),
    ],
)
def test_export_rejects_unsafe_next_before_a_second_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    next_value: object,
    message: str,
) -> None:
    session = _SequenceSession(
        [_Response({"count": 0, "results": [], "next": next_value})]
    )

    with pytest.raises(RuntimeError) as captured:
        _run_export(monkeypatch, tmp_path, session)

    assert str(captured.value) == message
    assert str(next_value) not in str(captured.value)
    assert len(session.calls) == 1


def test_export_detects_a_cycle_before_repeating_the_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    initial_query = "?language=2&limit=2&offset=0&ordering=id"
    session = _SequenceSession(
        [_Response({"count": 0, "results": [], "next": initial_query})]
    )

    with pytest.raises(RuntimeError, match="^Wger pagination cycle detected\\.$"):
        _run_export(monkeypatch, tmp_path, session)

    assert len(session.calls) == 1


def test_export_never_requests_page_1001(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class PagingSession:
        def __init__(self) -> None:
            self.calls = 0

        def __enter__(self) -> PagingSession:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, **kwargs: object) -> _Response:
            self.calls += 1
            return _Response({"count": 0, "results": [], "next": f"?page={self.calls}"})

    session = PagingSession()

    with pytest.raises(
        RuntimeError, match="^Wger pagination exceeded the 1000-page limit\\.$"
    ):
        _run_export(monkeypatch, tmp_path, session)

    assert session.calls == 1000


def test_export_preserves_a_smaller_operator_page_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = _SequenceSession(
        [
            _Response({"count": 2, "results": [{"id": 1}], "next": "?offset=1"}),
            _Response({"count": 2, "results": [{"id": 2}], "next": "?offset=2"}),
        ]
    )

    total, output = _run_export(monkeypatch, tmp_path, session, max_pages=1)

    assert total == 1
    assert json.loads(output.read_text(encoding="utf-8")) == [{"id": 1}]
    assert len(session.calls) == 1


def test_export_rejects_max_pages_above_the_security_ceiling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_calls = 0

    def unexpected_session() -> None:
        nonlocal session_calls
        session_calls += 1

    monkeypatch.setattr(exporter.requests, "Session", unexpected_session)

    with pytest.raises(
        RuntimeError, match="^Wger pagination exceeded the 1000-page limit\\.$"
    ):
        exporter.export_ingredients(
            base_url="https://fitness.example/wger/api/v2",
            language=2,
            limit=2,
            offset=0,
            output=tmp_path / "ingredients.json",
            auth_header=None,
            timeout=5.0,
            retries=0,
            max_pages=1001,
        )

    assert session_calls == 0


def test_export_redirect_fails_without_following_location(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = _SequenceSession([_Response({}, status_code=302)])

    with pytest.raises(
        RuntimeError, match="^Wger request redirects are not permitted\\.$"
    ):
        _run_export(monkeypatch, tmp_path, session)

    assert len(session.calls) == 1
    assert session.calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize(
    "base_url",
    ["file:///tmp/wger", "https://user:password@fitness.example/api/v2"],
)
def test_export_rejects_invalid_base_before_opening_a_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    base_url: str,
) -> None:
    session_calls = 0

    def unexpected_session() -> None:
        nonlocal session_calls
        session_calls += 1

    monkeypatch.setattr(exporter.requests, "Session", unexpected_session)

    with pytest.raises(RuntimeError) as captured:
        exporter.export_ingredients(
            base_url=base_url,
            language=2,
            limit=2,
            offset=0,
            output=tmp_path / "ingredients.json",
            auth_header=_GENERATED_AUTH_HEADER,
            timeout=5.0,
            retries=0,
            max_pages=None,
        )

    assert str(captured.value).startswith(
        "WGER_BASE_URL must be an absolute HTTP(S) URL"
    )
    assert base_url not in str(captured.value)
    assert session_calls == 0


def test_cli_rejects_max_pages_above_the_security_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        exporter,
        "parse_args",
        lambda: SimpleNamespace(limit=1, offset=0, max_pages=1001),
    )

    with pytest.raises(SystemExit, match="^--max-pages cannot exceed 1000$"):
        exporter.main()
