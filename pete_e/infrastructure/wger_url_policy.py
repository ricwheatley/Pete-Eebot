"""Pure URL policy for credential-bearing Wger requests."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import SplitResult, urlencode, urljoin, urlsplit, urlunsplit


INVALID_BASE_URL = "WGER_BASE_URL must be an absolute HTTP(S) URL without credentials, query, or fragment."
ORIGIN_MISMATCH = "Rejected Wger URL outside the configured origin."
INVALID_NEXT_URL = "Wger pagination returned an invalid next URL."
PAGINATION_CYCLE = "Wger pagination cycle detected."
PAGE_LIMIT_EXCEEDED = "Wger pagination exceeded the 1000-page limit."
REDIRECT_REJECTED = "Wger request redirects are not permitted."
MAX_PAGES = 1000

_ENCODED_AMBIGUOUS = frozenset("/\\?#@")
_HEX_PAIR = re.compile(r"^[0-9a-fA-F]{2}$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class WgerUrlPolicyError(ValueError):
    """A safe URL-policy failure whose message never includes rejected input."""


class InvalidWgerBaseUrl(WgerUrlPolicyError):
    """The configured base is not a supported absolute HTTP(S) URL."""


class InvalidWgerUrl(WgerUrlPolicyError):
    """A request or pagination reference is malformed or ambiguous."""


class WgerOriginMismatch(WgerUrlPolicyError):
    """A parsed request target does not belong to the configured origin."""


@dataclass(frozen=True)
class CanonicalOrigin:
    """A parsed origin using a canonical host and effective port."""

    scheme: str
    host: str
    port: int


@dataclass(frozen=True)
class WgerUrlPolicy:
    """Normalize one trusted Wger base and validate every later request URL."""

    base_url: str
    api_root: str
    origin: CanonicalOrigin

    @classmethod
    def from_base(cls, raw_url: str) -> WgerUrlPolicy:
        """Build a policy from the configured Wger base URL."""

        parts = _parse(raw_url, base=True)
        if "?" in raw_url or "#" in raw_url:
            raise InvalidWgerBaseUrl(INVALID_BASE_URL)

        origin, authority = _origin_and_authority(parts, base=True)
        base_path = parts.path.rstrip("/")
        if base_path.lower().endswith("/api/v2"):
            base_path = base_path[: -len("/api/v2")].rstrip("/")

        normalized_base = urlunsplit((origin.scheme, authority, base_path, "", ""))
        api_root = urlunsplit((origin.scheme, authority, f"{base_path}/api/v2", "", ""))
        return cls(base_url=normalized_base, api_root=api_root, origin=origin)

    def resolve_endpoint(self, reference: str) -> str:
        """Resolve an initial adapter endpoint against the configured API root."""

        parts = _parse(reference, base=False)
        if parts.scheme or parts.netloc:
            candidate = urljoin(f"{self.api_root}/", reference)
        else:
            candidate = f"{self.api_root}/{reference.lstrip('/')}"
        return self._validate_absolute(candidate)

    def resolve_pagination(self, current_url: str, reference: str) -> str:
        """Resolve a response-controlled link against the current page URL."""

        self._validate_absolute(current_url)
        _parse(reference, base=False)
        return self._validate_absolute(urljoin(current_url, reference))

    def request_url(self, url: str, params: Mapping[str, object] | None) -> str:
        """Return the canonical URL identity Requests will use for pagination."""

        validated = self._validate_absolute(url)
        if not params:
            return validated
        query = urlencode(params, doseq=True)
        separator = "&" if urlsplit(validated).query else "?"
        return f"{validated}{separator}{query}"

    def _validate_absolute(self, raw_url: str) -> str:
        parts = _parse(raw_url, base=False)
        if not parts.scheme or not parts.netloc:
            raise InvalidWgerUrl(INVALID_NEXT_URL)

        candidate_origin, authority = _origin_and_authority(parts, base=False)
        if candidate_origin != self.origin:
            raise WgerOriginMismatch(ORIGIN_MISMATCH)

        return urlunsplit(
            (
                candidate_origin.scheme,
                authority,
                parts.path,
                parts.query,
                "",
            )
        )


def _parse(raw_url: str, *, base: bool) -> SplitResult:
    error_type = InvalidWgerBaseUrl if base else InvalidWgerUrl
    error_message = INVALID_BASE_URL if base else INVALID_NEXT_URL
    if not isinstance(raw_url, str) or not raw_url or _is_ambiguous(raw_url):
        raise error_type(error_message)
    if raw_url.startswith("///"):
        raise error_type(error_message)

    try:
        parts = urlsplit(raw_url)
        _ = parts.hostname
        _ = parts.port
    except (UnicodeError, ValueError):
        raise error_type(error_message) from None

    if parts.fragment or "#" in raw_url or "@" in parts.netloc:
        raise error_type(error_message)
    if parts.scheme and parts.scheme.lower() not in {"http", "https"}:
        raise error_type(error_message)
    if (parts.scheme and not parts.netloc) or (
        raw_url.startswith("//") and not parts.netloc
    ):
        raise error_type(error_message)
    if base and (not parts.scheme or not parts.netloc):
        raise error_type(error_message)
    return parts


def _is_ambiguous(raw_url: str) -> bool:
    if "\\" in raw_url or any(
        character.isspace() or ord(character) < 32 or 127 <= ord(character) <= 159
        for character in raw_url
    ):
        return True

    offset = 0
    while True:
        offset = raw_url.find("%", offset)
        if offset < 0:
            return False
        pair = raw_url[offset + 1 : offset + 3]
        if not _HEX_PAIR.fullmatch(pair):
            return True
        decoded = chr(int(pair, 16))
        if (
            ord(decoded) < 32
            or 127 <= ord(decoded) <= 159
            or decoded in _ENCODED_AMBIGUOUS
        ):
            return True
        offset += 3


def _origin_and_authority(
    parts: SplitResult, *, base: bool
) -> tuple[CanonicalOrigin, str]:
    error_type = InvalidWgerBaseUrl if base else InvalidWgerUrl
    error_message = INVALID_BASE_URL if base else INVALID_NEXT_URL
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or parts.hostname is None:
        raise error_type(error_message)

    try:
        host, is_ipv6 = _canonical_host(parts.hostname)
        parsed_port = parts.port
    except (UnicodeError, ValueError):
        raise error_type(error_message) from None

    effective_port = (
        parsed_port if parsed_port is not None else (443 if scheme == "https" else 80)
    )
    if effective_port < 1 or effective_port > 65535:
        raise error_type(error_message)

    rendered_host = f"[{host}]" if is_ipv6 else host
    default_port = 443 if scheme == "https" else 80
    authority = (
        rendered_host
        if effective_port == default_port
        else f"{rendered_host}:{effective_port}"
    )
    return CanonicalOrigin(scheme, host, effective_port), authority


def _canonical_host(raw_host: str) -> tuple[str, bool]:
    if "%" in raw_host:
        raise ValueError("zone identifiers are not supported")

    host = raw_host
    if host.endswith("."):
        host = host[:-1]
        if not host or host.endswith("."):
            raise ValueError("only one terminal DNS dot is supported")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if ":" in host or all(
            character.isdigit() or character == "." for character in host
        ):
            raise
    else:
        return address.compressed.lower(), address.version == 6

    ascii_host = host.encode("idna").decode("ascii").lower()
    if len(ascii_host) > 253 or any(
        not _DNS_LABEL.fullmatch(label) for label in ascii_host.split(".")
    ):
        raise ValueError("invalid DNS hostname")
    return ascii_host, False
