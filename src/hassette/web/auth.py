"""Token resolution and trusted-proxy peer matching for the web API's auth mechanisms.

Two independent pieces live here:

- Token resolution for the bearer-token/session-cookie fallback: resolves the credential used
  by ``AuthDep``/the default-deny middleware (built in later tasks) to validate
  ``Authorization: Bearer <token>`` headers and mint session cookies.
- ``trusted_proxies`` peer matching: parses each config entry as an IP, CIDR, or hostname, and
  exposes :func:`is_trusted_peer` to check a raw ASGI peer address against the resolved set.
  ``is_trusted_peer`` accepts only an address string — never a headers mapping or request
  object — so header-spoofed trust is not representable at this layer.

See ``design/specs/091-web-api-auth/design.md`` (Architecture → Credential model) for the full
mechanism this implements.
"""

import ipaddress
import os
import secrets
import socket
from contextlib import suppress
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path

from hassette.config.models import WebApiConfig
from hassette.exceptions import AuthTokenWriteError, TrustedProxyConfigError

LOGGER = getLogger(__name__)

TOKEN_FILENAME = ".web_api_token"  # noqa: S105 — a filename, not a hardcoded credential
"""Name of the persisted token file, relative to ``data_dir``."""

TOKEN_BYTE_LENGTH = 32
"""Byte length passed to ``secrets.token_urlsafe()`` when generating a fresh token."""

_ENTIRE_ADDRESS_SPACE = (ipaddress.ip_network("0.0.0.0/0"), ipaddress.ip_network("::/0"))
"""The two CIDRs that match every possible peer address.

Rejected outright at parse time (see :func:`_parse_literal`) — a ``trusted_proxies`` entry is an
auth *bypass*, not an additive check, so a config value matching the entire address space would
disable authentication for every peer. This is a narrow, exact-match rejection of these two
literal networks, not a general "is this CIDR suspiciously broad" heuristic; a ``/8`` or ``/16``
entry is a legitimate (if unusual) operator choice and is not rejected.
"""


def resolve_auth_token(config: WebApiConfig, data_dir: Path) -> str:
    """Resolve the web API's bearer-token/session-cookie credential.

    Tries, in order:

    1. ``config.auth_token`` if explicitly configured (non-``None``).
    2. An existing ``<data_dir>/.web_api_token`` file. A corrupt or unreadable file
       (empty, undecodable, or an OS-level read failure) is treated identically to
       "no file exists" — the failure is logged at ERROR and resolution falls through
       to step 3 rather than crashing.
    3. A freshly generated ``secrets.token_urlsafe(32)`` value, persisted atomically
       (temp file in the same directory + atomic rename, mode ``0600``) to
       ``<data_dir>/.web_api_token``.

    Whichever branch fires is logged at INFO with a distinct, identifiable message on
    every startup, not only the generate branch — so an operator who lost a
    previously-working token file (volume not migrated, ``docker compose down -v``) sees
    "loaded existing file" vs. "generated a new one" as a distinguishable event, not
    silence.

    Args:
        config: The web API config. Its ``host``/``port`` are used to build the
            ready-to-use login URL logged on the generate branch.
        data_dir: Directory the token file is read from/written to. Callers pass
            ``HassetteConfig.data_dir`` — this function does not resolve it itself.

    Returns:
        The plaintext token, unwrapped from ``SecretStr`` when it came from config.

    Raises:
        AuthTokenWriteError: The freshly generated token could not be persisted to disk
            (permissions, read-only filesystem, full disk). Startup fails loudly rather
            than falling back to an ephemeral in-memory token — see the exception's
            docstring for why silent fallback is unacceptable here.
    """
    if config.auth_token is not None:
        LOGGER.info("Using configured web API auth_token")
        return config.auth_token.get_secret_value()

    token_path = data_dir / TOKEN_FILENAME
    existing_token = _read_existing_token(token_path)
    if existing_token is not None:
        LOGGER.info("Loaded existing web API auth_token from %s", token_path)
        return existing_token

    token = secrets.token_urlsafe(TOKEN_BYTE_LENGTH)
    _write_token_atomic(token_path, token)
    login_url = f"http://{config.host}:{config.port}"
    LOGGER.info(
        "Generated new web API auth_token, written to %s. Open %s to log in.",
        token_path,
        login_url,
    )
    return token


def _read_existing_token(token_path: Path) -> str | None:
    """Read an existing token file, treating a corrupt/unreadable file as "no file".

    Returns ``None`` (never raises) when the file doesn't exist, is empty, contains
    undecodable bytes, or otherwise fails to read — each of those is logged at ERROR
    so the fallback to a fresh token is visible, not silent.
    """
    if not token_path.exists():
        return None

    try:
        content = token_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        LOGGER.exception(
            "Web API auth token file %s could not be read; generating a new token",
            token_path,
        )
        return None

    if not content:
        LOGGER.error(
            "Web API auth token file %s is empty; generating a new token",
            token_path,
        )
        return None

    return content


def _write_token_atomic(token_path: Path, token: str) -> None:
    """Write ``token`` to ``token_path`` atomically, mode ``0600``.

    Writes to a temp file in the same directory as ``token_path`` (not ``/tmp``, which
    may be a different filesystem and would break the rename's atomicity guarantee),
    then swaps it into place with ``Path.replace()`` (an atomic rename on POSIX). Any
    failure along the way (including creating the parent directory) is wrapped in
    ``AuthTokenWriteError`` naming the exact path and OS error, and any
    partially-written temp file is cleaned up on a best-effort basis.
    """
    tmp_path = token_path.with_name(f"{token_path.name}.tmp-{os.getpid()}")
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
        tmp_path.replace(token_path)
    except OSError as exc:
        with suppress(OSError):
            tmp_path.unlink()
        raise AuthTokenWriteError(token_path, exc) from exc


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
    hostname_entries: dict[str, frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network]]

    def all_networks(self) -> frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        """Return every currently-trusted network: literals plus all resolved hostnames."""
        combined: set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set(self.literal_networks)
        for networks in self.hostname_entries.values():
            combined |= networks
        return frozenset(combined)


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


def _resolve_hostname(hostname: str) -> frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Resolve ``hostname`` via ``socket.getaddrinfo``, returning each address as a /32 or /128 network.

    Raises:
        TrustedProxyConfigError: DNS resolution failed, or resolved to zero addresses.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise TrustedProxyConfigError(
            f"trusted_proxies entry {hostname!r} is not a valid IP/CIDR literal and could not be "
            f"resolved as a hostname: {exc}"
        ) from exc

    networks = {ipaddress.ip_network(info[4][0], strict=False) for info in infos}
    if not networks:
        raise TrustedProxyConfigError(f"trusted_proxies entry {hostname!r} resolved to no addresses")
    return frozenset(networks)


def resolve_trusted_proxies(entries: tuple[str, ...]) -> TrustedProxySet:
    """Parse and resolve every ``trusted_proxies`` config entry.

    Called once at startup (``WebApiService.on_initialize()``). Each entry is tried as an
    IP/CIDR literal first (fast, no DNS); entries that aren't valid literals are resolved as
    hostnames via DNS. Failure at this first resolution — a malformed literal, an
    entire-address-space CIDR, or an unresolvable hostname — fails loudly rather than silently
    dropping the bad entry, since a wrong ``trusted_proxies`` entry is a security-relevant
    misconfiguration (design.md Edge Cases, "A trusted_proxies entry that's wrong or too broad").

    Args:
        entries: ``WebApiConfig.trusted_proxies`` — IP, CIDR, or hostname strings.

    Returns:
        The resolved :class:`TrustedProxySet`.

    Raises:
        TrustedProxyConfigError: Any entry is neither a valid IP/CIDR literal nor a resolvable
            hostname, or a literal matches the entire address space.
    """
    literal_networks: set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set()
    hostname_entries: dict[str, frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network]] = {}
    for entry in entries:
        network = _parse_literal(entry)
        if network is not None:
            literal_networks.add(network)
            continue
        hostname_entries[entry] = _resolve_hostname(entry)
    return TrustedProxySet(literal_networks=frozenset(literal_networks), hostname_entries=hostname_entries)


def refresh_trusted_proxies(current: TrustedProxySet) -> TrustedProxySet:
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
            updated[hostname] = _resolve_hostname(hostname)
        except TrustedProxyConfigError:
            LOGGER.warning(
                "Could not refresh trusted_proxies hostname %r; keeping last-known-good address(es)",
                hostname,
            )
            updated[hostname] = previous_networks
    return TrustedProxySet(literal_networks=current.literal_networks, hostname_entries=updated)


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
