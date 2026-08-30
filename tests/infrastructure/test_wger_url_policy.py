from __future__ import annotations

import pytest

from pete_e.infrastructure.wger_url_policy import (
    INVALID_BASE_URL,
    INVALID_NEXT_URL,
    ORIGIN_MISMATCH,
    CanonicalOrigin,
    InvalidWgerBaseUrl,
    InvalidWgerUrl,
    WgerOriginMismatch,
    WgerUrlPolicy,
)


@pytest.mark.parametrize(
    ("raw_url", "base_url", "api_root", "origin"),
    [
        (
            "https://wger.de/api/v2",
            "https://wger.de",
            "https://wger.de/api/v2",
            CanonicalOrigin("https", "wger.de", 443),
        ),
        (
            "HTTPS://Fitness.Example.:443/wger/api/v2///",
            "https://fitness.example/wger",
            "https://fitness.example/wger/api/v2",
            CanonicalOrigin("https", "fitness.example", 443),
        ),
        (
            "http://127.0.0.1:8080/prefix",
            "http://127.0.0.1:8080/prefix",
            "http://127.0.0.1:8080/prefix/api/v2",
            CanonicalOrigin("http", "127.0.0.1", 8080),
        ),
        (
            "http://[2001:0DB8::1]:80/api/v2/",
            "http://[2001:db8::1]",
            "http://[2001:db8::1]/api/v2",
            CanonicalOrigin("http", "2001:db8::1", 80),
        ),
        (
            "https://BÜCHER.example/wger",
            "https://xn--bcher-kva.example/wger",
            "https://xn--bcher-kva.example/wger/api/v2",
            CanonicalOrigin("https", "xn--bcher-kva.example", 443),
        ),
    ],
)
def test_base_url_is_canonicalized_once(
    raw_url: str,
    base_url: str,
    api_root: str,
    origin: CanonicalOrigin,
) -> None:
    policy = WgerUrlPolicy.from_base(raw_url)

    assert policy.base_url == base_url
    assert policy.api_root == api_root
    assert policy.origin == origin


@pytest.mark.parametrize(
    "raw_url",
    [
        "",
        "wger.de/api/v2",
        "file:///tmp/wger",
        "https:///api/v2",
        "https://:443/api/v2",
        "https://user:password@example.test/api/v2",
        "https://example.test/api/v2?limit=1",
        "https://example.test/api/v2?",
        "https://example.test/api/v2#fragment",
        "https://example.test/api/v2#",
        "https://example.test/white space",
        "https://example.test/control\n",
        "https://example.test/control\x00",
        "https://example.test\\collect",
        "https://example.test/%2fcollect",
        "https://example.test/%00collect",
        "https://example.test/%80collect",
        "https://example.test/%zz",
        "https://[2001:db8::1/api/v2",
        "https://example.test:not-a-port/api/v2",
        "https://example.test:0/api/v2",
        "https://example.test:65536/api/v2",
        "https://[fe80::1%25eth0]/api/v2",
        "https://example.test../api/v2",
        "https://bad_host.test/api/v2",
        "https://-bad.test/api/v2",
        "https://127.000.000.001/api/v2",
        "///example.test/api/v2",
    ],
)
def test_invalid_bases_fail_with_one_safe_error(raw_url: str) -> None:
    with pytest.raises(InvalidWgerBaseUrl) as captured:
        WgerUrlPolicy.from_base(raw_url)

    assert str(captured.value) == INVALID_BASE_URL
    if raw_url:
        assert raw_url not in str(captured.value)


def test_non_string_base_is_rejected_safely() -> None:
    with pytest.raises(InvalidWgerBaseUrl, match="^WGER_BASE_URL"):
        WgerUrlPolicy.from_base(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("routine/", "https://wger.de/api/v2/routine/"),
        ("/routine/", "https://wger.de/api/v2/routine/"),
        ("https://WGER.DE:443/api/v2/routine/", "https://wger.de/api/v2/routine/"),
        ("//wger.de./api/v2/routine/", "https://wger.de/api/v2/routine/"),
    ],
)
def test_initial_endpoints_remain_on_the_configured_origin(
    reference: str,
    expected: str,
) -> None:
    assert (
        WgerUrlPolicy.from_base("https://wger.de/api/v2").resolve_endpoint(reference)
        == expected
    )


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("?offset=2", "https://wger.de/api/v2/items/?offset=2"),
        ("next/", "https://wger.de/api/v2/items/next/"),
        ("/api/v2/other/", "https://wger.de/api/v2/other/"),
        ("//WGER.DE.:443/api/v2/other/", "https://wger.de/api/v2/other/"),
        ("https://wger.de:443/api/v2/other/", "https://wger.de/api/v2/other/"),
    ],
)
def test_pagination_resolves_against_the_current_page(
    reference: str, expected: str
) -> None:
    policy = WgerUrlPolicy.from_base("https://wger.de/api/v2")

    assert (
        policy.resolve_pagination("https://wger.de/api/v2/items/?offset=1", reference)
        == expected
    )


@pytest.mark.parametrize(
    "reference",
    [
        "http://wger.de/api/v2/items/",
        "https://pagination.invalid/api/v2/items/",
        "https://sub.wger.de/api/v2/items/",
        "https://wger.de:444/api/v2/items/",
        "//pagination.invalid/api/v2/items/",
    ],
)
def test_origin_changes_are_rejected(reference: str) -> None:
    policy = WgerUrlPolicy.from_base("https://wger.de/api/v2")

    with pytest.raises(WgerOriginMismatch) as captured:
        policy.resolve_pagination("https://wger.de/api/v2/items/", reference)

    assert str(captured.value) == ORIGIN_MISMATCH
    assert reference not in str(captured.value)


@pytest.mark.parametrize(
    "reference",
    [
        "https://user:password@wger.de/api/v2/items/",
        "https://wger.de/api/v2/items/#fragment",
        "https://wger.de/api/v2/items/#",
        " https://wger.de/api/v2/items/",
        "https://wger.de/api/v2/items\\next",
        "https://wger.de/api/v2/%2fnext",
        "https://wger.de/api/v2/%0anext",
        "https://wger.de/api/v2/%",
        "https://[::1",
        "https://wger.de:bad/api/v2/items/",
        "https:///api/v2/items/",
        "http:/api/v2/items/",
        "file:///tmp/items",
        "//",
        "///pagination.invalid/items",
    ],
)
def test_malformed_references_are_rejected(reference: str) -> None:
    policy = WgerUrlPolicy.from_base("https://wger.de/api/v2")

    with pytest.raises(InvalidWgerUrl) as captured:
        policy.resolve_pagination("https://wger.de/api/v2/items/", reference)

    assert str(captured.value) == INVALID_NEXT_URL
    assert reference not in str(captured.value)


def test_relative_current_url_is_rejected() -> None:
    policy = WgerUrlPolicy.from_base("https://wger.de/api/v2")

    with pytest.raises(InvalidWgerUrl, match="^Wger pagination"):
        policy.resolve_pagination("/items/", "?offset=2")


def test_request_url_adds_params_without_replacing_an_existing_query() -> None:
    policy = WgerUrlPolicy.from_base("https://wger.de/api/v2")

    assert policy.request_url("https://wger.de/api/v2/items/", None).endswith("/items/")
    assert policy.request_url(
        "https://wger.de/api/v2/items/",
        {"limit": 2, "tag": ["a", "b"]},
    ).endswith("/items/?limit=2&tag=a&tag=b")
    assert policy.request_url(
        "https://wger.de/api/v2/items/?offset=2",
        {"limit": 2},
    ).endswith("/items/?offset=2&limit=2")
