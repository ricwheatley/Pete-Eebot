"""Resolve a request's client address across an explicitly trusted proxy chain."""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Any, Iterable

from pete_e.config import settings


MAX_FORWARDED_HOPS = 20


def _configured_networks(raw_value: str | None = None):
    raw = (
        str(getattr(settings, "PETEEEBOT_TRUSTED_PROXY_CIDRS", "") or "")
        if raw_value is None
        else str(raw_value)
    )
    networks = []
    for value in raw.split(","):
        candidate = value.strip()
        if candidate:
            networks.append(ip_network(candidate, strict=False))
    return tuple(networks)


def _is_trusted(address, networks: Iterable[Any]) -> bool:
    return any(address.version == network.version and address in network for network in networks)


def _header_value(request: Any, name: str) -> str | None:
    headers = getattr(request, "headers", {}) or {}
    value = headers.get(name.lower()) or headers.get(name)
    return str(value) if value is not None else None


def _immediate_peer(request: Any) -> str:
    client = getattr(request, "client", None)
    host = str(getattr(client, "host", "") or "").strip()
    return host or "local"


def resolve_client_identity(request: Any, *, trusted_proxy_cidrs: str | None = None) -> str:
    """Return the first untrusted hop, ignoring XFF from an untrusted peer.

    A malformed chain from a trusted peer deliberately collapses to the immediate
    peer. That can aggregate callers behind a proxy, but cannot let attacker input
    manufacture new rate-limit or audit identities.
    """

    peer_text = _immediate_peer(request)
    try:
        peer = ip_address(peer_text)
        networks = _configured_networks(trusted_proxy_cidrs)
    except ValueError:
        return peer_text

    if not _is_trusted(peer, networks):
        return peer.compressed

    forwarded_for = _header_value(request, "X-Forwarded-For")
    if not forwarded_for:
        return peer.compressed

    raw_hops = [part.strip() for part in forwarded_for.split(",")]
    if not raw_hops or len(raw_hops) > MAX_FORWARDED_HOPS or any(not hop for hop in raw_hops):
        return peer.compressed
    try:
        forwarded_hops = [ip_address(hop) for hop in raw_hops]
    except ValueError:
        return peer.compressed

    current = peer
    for forwarded_hop in reversed(forwarded_hops):
        if not _is_trusted(current, networks):
            break
        current = forwarded_hop
    return current.compressed


def client_identity(request: Any) -> str:
    """Resolve and memoize the security/audit identity for one request."""

    state = getattr(request, "state", None)
    cached = getattr(state, "client_identity", None) if state is not None else None
    if cached:
        return str(cached)
    resolved = resolve_client_identity(request)
    if state is not None:
        setattr(state, "client_identity", resolved)
    return resolved


__all__ = ["MAX_FORWARDED_HOPS", "client_identity", "resolve_client_identity"]
