"""Trusted-proxy peer matching for the web API's default-deny auth gate.

Parses each ``trusted_proxies`` config entry as an IP, CIDR, or hostname, and exposes
:func:`is_trusted_peer` to check a raw ASGI peer address against the resolved set.
``is_trusted_peer`` accepts only an address string — never a headers mapping or request
object — so header-spoofed trust is not representable at this layer. See
``design/specs/091-web-api-auth/design.md`` (Architecture → Credential model) for the full
mechanism this implements.
"""

import asyncio
import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass
from logging import getLogger
from types import MappingProxyType

from starlette.datastructures import State
from starlette.requests import HTTPConnection, Request

from hassette.exceptions import TrustedProxyConfigError

LOGGER = getLogger(__name__)

_ENTIRE_ADDRESS_SPACE = (ipaddress.ip_network("0.0.0.0/0"), ipaddress.ip_network("::/0"))
"""The two CIDRs that match every possible peer address.

Rejected outright at parse time (see :func:`_parse_literal`) — a ``trusted_proxies`` entry is an
auth *bypass*, not an additive check, so a config value matching the entire address space would
disable authentication for every peer. This is a narrow, exact-match rejection of these two
literal networks, not a general "is this CIDR suspiciously broad" heuristic; a ``/8`` or ``/16``
entry is a legitimate (if unusual) operator choice and is not rejected.
"""

_DNS_RESOLVE_TIMEOUT_SECONDS = 5
"""Upper bound on a single ``trusted_proxies`` hostname DNS resolution.

``_resolve_hostname`` is reachable from a recurring ``Scheduler.run_every()`` job
(:func:`refresh_trusted_proxies`, invoked every 5 minutes from
``WebApiService._refresh_trusted_proxies``) as well as startup (:func:`resolve_trusted_proxies`).
Without an explicit deadline, a slow or unreachable resolver would leave the awaiting coroutine
(and, on the refresh path, that scheduler tick) hanging for however long the OS resolver takes to
give up — this bounds the wait instead of trusting the OS default.
"""

_HOSTNAME_LABEL = r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?"
_HOSTNAME_PATTERN = re.compile(rf"(?:{_HOSTNAME_LABEL}\.)*{_HOSTNAME_LABEL}\.?")
"""Syntactic shape of a DNS hostname: dot-separated labels of letters, digits, ``-`` and ``_``.

Underscores are allowed because Docker Compose service names (``my_proxy``) may contain them, and
those names are exactly what a self-managed deployment lists. :func:`_validate_hostname` applies
this together with the length and IPv4-shaped checks.
"""

_MAX_HOSTNAME_LENGTH = 253


class HostnameResolutionError(Exception):
    """A syntactically valid ``trusted_proxies`` hostname did not resolve right now.

    Distinct from :class:`~hassette.exceptions.TrustedProxyConfigError`: a DNS miss (NXDOMAIN, a
    resolver timeout, zero addresses) is a transient runtime condition, not a config error. Callers
    keep the entry with its last-known-good networks (or none) and let the periodic refresh retry.
    """


@dataclass(frozen=True)
class TrustedProxySet:
    """Resolved ``trusted_proxies`` state: literal IP/CIDR entries plus current hostname resolutions.

    Immutable — :func:`refresh_trusted_proxies` returns a new instance rather than mutating this
    one, so a periodic ``Scheduler.run_every()`` refresh can swap in an updated set with a
    single attribute assignment, no lock required around in-place mutation.

    Attributes:
        literal_networks: Networks parsed directly from IP/CIDR entries. Never changes after the
            initial :func:`resolve_trusted_proxies` call — literals don't need re-resolution.
        hostname_entries: Maps each hostname entry to its currently-resolved networks. Updated by
            :func:`refresh_trusted_proxies` on each periodic tick.
    """

    literal_networks: frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network]
    hostname_entries: Mapping[str, frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network]]

    def all_networks(self) -> frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        """Return every currently-trusted network: literals plus all resolved hostnames."""
        combined: set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set(self.literal_networks)
        for networks in self.hostname_entries.values():
            combined |= networks
        return frozenset(combined)


EMPTY_TRUSTED_PROXY_SET = TrustedProxySet(literal_networks=frozenset(), hostname_entries=MappingProxyType({}))
"""A :class:`TrustedProxySet` that matches no peer address.

Used as the fallback wherever a resolved trusted-proxy set is read from ``app.state`` but wasn't
provided (e.g. a test app built via ``create_fastapi_app(hassette)`` with no ``trusted_proxies``
argument, or ``trusted_proxies=()`` in config) — ``is_trusted_peer`` against this always returns
``False`` rather than the caller needing a ``None``/``AttributeError`` guard at every call site.
"""


def get_trusted_proxies(state: State) -> TrustedProxySet:
    """Resolve the trusted-proxy set off ASGI app state, defaulting to :data:`EMPTY_TRUSTED_PROXY_SET`.

    Shared by :class:`~hassette.web.middleware.DefaultDenyMiddleware`, :func:`~hassette.web.auth.authorize_ws`, and
    ``POST /api/auth/session`` (``web/routes/auth.py``) — all three need the same
    lookup-with-fallback for ``app.state.trusted_proxies``, set by
    :func:`hassette.web.app.create_fastapi_app`.
    """
    return getattr(state, "trusted_proxies", None) or EMPTY_TRUSTED_PROXY_SET


def peer_address(connection: HTTPConnection) -> str | None:
    """Raw ASGI peer address for ``connection``, or ``None`` if the transport reports no client.

    Takes the ``HTTPConnection`` base rather than ``Request`` so the WebSocket handshake
    (:func:`~hassette.web.auth.authorize_ws`) reads its peer through the same function the HTTP paths use —
    :class:`~hassette.web.middleware.DefaultDenyMiddleware` and ``POST /api/auth/session``
    (``web/routes/auth.py``) — instead of repeating the null-safe ``client.host`` extraction.
    """
    client = connection.client
    return client.host if client is not None else None


def peer_address_or_unknown(request: Request) -> str:
    """:func:`peer_address`, falling back to the literal ``"unknown"`` when the transport reports no client.

    Shared by every route handler that logs a source IP alongside a mutation action
    (``web/routes/apps.py``, ``web/routes/logs.py``, ``web/routes/scheduler.py``) and by the
    default-deny middleware's failed-auth source key (``web/middleware.py``) — all of these want
    the same null-safe fallback rather than repeating ``peer_address(request) or "unknown"`` at
    each call site.
    """
    return peer_address(request) or "unknown"


def _parse_literal(entry: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """Parse ``entry`` as an IP or CIDR literal via :mod:`ipaddress`.

    Returns:
        The parsed network, or ``None`` if ``entry`` is not a valid IP/CIDR literal — the caller
        falls through to hostname resolution in that case.

    Raises:
        TrustedProxyConfigError: ``entry`` parses but matches the entire IPv4 or IPv6 address
            space (``0.0.0.0/0``, ``::/0``) — see :data:`_ENTIRE_ADDRESS_SPACE`.
    """
    try:
        network = ipaddress.ip_network(entry, strict=False)
    except ValueError:
        return None

    if network in _ENTIRE_ADDRESS_SPACE:
        raise TrustedProxyConfigError(
            f"trusted_proxies entry {entry!r} matches the entire address space, which would "
            "bypass authentication for every peer. Use a narrower CIDR."
        )
    return network


def _validate_hostname(entry: str) -> None:
    """Reject an entry that is neither an IP/CIDR literal nor a syntactically valid hostname.

    Runs before any DNS lookup so a typo (``10.0.0.300``, ``proxy!``, an empty string) fails startup
    as a config error instead of being retried forever as an unresolved hostname. An entry whose
    labels are all digits (``10.0.0.300``, ``10.0.300``) is IPv4-shaped, so it is rejected as a
    malformed IP literal. A name with only a numeric final label (``proxy.123``) is still a valid
    private DNS name and is left for the resolver.

    Raises:
        TrustedProxyConfigError: ``entry`` is not a valid hostname.
    """
    labels = entry.rstrip(".").split(".")
    if (
        len(entry) > _MAX_HOSTNAME_LENGTH
        or not _HOSTNAME_PATTERN.fullmatch(entry)
        or all(label.isdigit() for label in labels)
    ):
        raise TrustedProxyConfigError(
            f"trusted_proxies entry {entry!r} is neither a valid IP/CIDR literal nor a valid hostname"
        )


async def _resolve_hostname(hostname: str) -> frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Resolve ``hostname`` via the running event loop's resolver, returning each address as a /32 or /128 network.

    Uses ``loop.getaddrinfo`` rather than calling ``socket.getaddrinfo`` directly — the latter is a
    blocking call, and this function runs on the event loop thread from both call sites: startup
    (:func:`resolve_trusted_proxies`, from ``WebApiService.on_initialize()``) and the periodic
    refresh job (:func:`refresh_trusted_proxies`, an ``async def`` scheduler job body). A blocking
    resolver call there would stall the whole event loop — the web API, the Home Assistant
    WebSocket, and every other scheduled job — for as long as DNS takes to respond or time out.
    ``loop.getaddrinfo`` offloads the actual blocking call to a worker thread, and the wait is
    additionally bounded by :data:`_DNS_RESOLVE_TIMEOUT_SECONDS` so a hung resolver fails fast
    instead of blocking this coroutine indefinitely.

    Raises:
        HostnameResolutionError: DNS resolution failed, timed out, or resolved to zero addresses.
    """
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(_DNS_RESOLVE_TIMEOUT_SECONDS):
            infos = await loop.getaddrinfo(hostname, None)
    except (OSError, TimeoutError) as exc:
        raise HostnameResolutionError(str(exc) or type(exc).__name__) from exc

    networks = {ipaddress.ip_network(info[4][0], strict=False) for info in infos}
    if not networks:
        raise HostnameResolutionError("resolved to no addresses")
    return frozenset(networks)


async def resolve_trusted_proxies(
    entries: tuple[str, ...], previous: TrustedProxySet = EMPTY_TRUSTED_PROXY_SET
) -> TrustedProxySet:
    """Parse and resolve every ``trusted_proxies`` config entry.

    Called from ``WebApiService.on_initialize()``, at startup and again on every service restart.
    Each entry is tried as an IP/CIDR literal first (fast, no DNS); any other entry must be a
    syntactically valid hostname. Every entry is validated before any DNS lookup runs, so a config
    error fails fast: a malformed literal, an entire-address-space CIDR, or an empty entry raises
    rather than being silently dropped (design.md Edge Cases, "A trusted_proxies entry that's wrong
    or too broad").

    A valid hostname that doesn't resolve right now (NXDOMAIN, resolver timeout) is not a config
    error — a Compose sibling may simply not have registered with Docker's DNS yet. That entry keeps
    its networks from ``previous`` (none at first startup, so it fails closed and trusts no peer), a
    warning is logged, and the periodic :func:`refresh_trusted_proxies` job picks it up once DNS
    answers.

    Args:
        entries: ``WebApiConfig.trusted_proxies`` — IP, CIDR, or hostname strings.
        previous: The set resolved before a ``WebApiService`` restart, so a restart during a DNS
            outage keeps last-known-good resolutions instead of starting from nothing.

    Returns:
        The resolved :class:`TrustedProxySet`.

    Raises:
        TrustedProxyConfigError: Any entry is neither a valid IP/CIDR literal nor a valid hostname,
            or a literal matches the entire address space.
    """
    literal_networks: set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set()
    hostnames: list[str] = []
    for entry in entries:
        network = _parse_literal(entry)
        if network is not None:
            literal_networks.add(network)
            continue
        _validate_hostname(entry)
        hostnames.append(entry)

    hostname_entries: dict[str, frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network]] = {}
    for hostname in hostnames:
        try:
            hostname_entries[hostname] = await _resolve_hostname(hostname)
        except HostnameResolutionError as exc:
            fallback = previous.hostname_entries.get(hostname, frozenset())
            LOGGER.warning(
                "trusted_proxies hostname %r did not resolve (%s); %s until a periodic refresh resolves it",
                hostname,
                exc,
                "keeping last-known-good address(es)" if fallback else "trusting no peer for it",
            )
            hostname_entries[hostname] = fallback
    return TrustedProxySet(
        literal_networks=frozenset(literal_networks), hostname_entries=MappingProxyType(hostname_entries)
    )


async def refresh_trusted_proxies(current: TrustedProxySet) -> TrustedProxySet:
    """Re-resolve every hostname entry in ``current``; literal entries are unchanged.

    Called periodically (``Scheduler.run_every()``) so a sibling proxy container recreated
    mid-run (new IP, same hostname) becomes trusted again on the next tick. A hostname whose
    refresh attempt fails keeps its last-known-good resolved addresses rather than dropping trust
    immediately — a transient DNS blip must not lock out the proxy (design.md Edge Cases,
    "trusted_proxies DNS resolution failure").

    Args:
        current: The previously-resolved set, as returned by :func:`resolve_trusted_proxies` or
            a prior call to this function.

    Returns:
        A new :class:`TrustedProxySet` with refreshed hostname resolutions. Never raises — a
        failed refresh for one hostname is logged and that hostname's prior networks are carried
        forward unchanged.
    """
    updated: dict[str, frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network]] = {}
    for hostname, previous_networks in current.hostname_entries.items():
        try:
            updated[hostname] = await _resolve_hostname(hostname)
        except HostnameResolutionError as exc:
            LOGGER.warning(
                "Could not refresh trusted_proxies hostname %r (%s); keeping last-known-good address(es)",
                hostname,
                exc,
            )
            updated[hostname] = previous_networks
    return TrustedProxySet(literal_networks=current.literal_networks, hostname_entries=MappingProxyType(updated))


def is_trusted_peer(client_address: str, trusted: TrustedProxySet) -> bool:
    """Check whether ``client_address`` matches a trusted-proxy IP, CIDR, or resolved hostname.

    ``client_address`` must be the raw ASGI ``scope["client"]`` peer address — never a value
    read from ``X-Forwarded-For`` or any other client-suppliable header. This function's
    signature is itself the load-bearing guarantee here: there is no headers parameter, so header-spoofed
    trust is not representable at this layer.

    Args:
        client_address: The direct peer's IP address, as a string.
        trusted: The current resolved trust set.

    Returns:
        ``True`` if ``client_address`` falls within any trusted network; ``False`` if it doesn't,
        or if ``client_address`` itself isn't a parseable IP address.
    """
    try:
        addr = ipaddress.ip_address(client_address)
    except ValueError:
        return False
    return any(addr in network for network in trusted.all_networks())
