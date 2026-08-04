"""Token resolution, trusted-proxy peer matching, and bearer/cookie auth for the web API.

Three independent pieces live here:

- Token resolution for the bearer-token/session-cookie fallback: resolves the credential used
  by ``AuthDep``/the default-deny middleware (built in later tasks) to validate
  ``Authorization: Bearer <token>`` headers and mint session cookies.
- ``trusted_proxies`` peer matching: parses each config entry as an IP, CIDR, or hostname, and
  exposes :func:`is_trusted_peer` to check a raw ASGI peer address against the resolved set.
  ``is_trusted_peer`` accepts only an address string — never a headers mapping or request
  object — so header-spoofed trust is not representable at this layer.
- Bearer-token/session-cookie auth: :func:`check_bearer_token` (timing-safe comparison),
  :func:`mint_session_cookie`/:func:`verify_session_cookie` (stateless, HMAC-derived cookie
  keyed by the resolved token), :func:`should_set_secure_cookie_flag` (reuses
  :func:`is_trusted_peer` to decide the cookie's ``Secure`` attribute), and
  :func:`should_renew_session_cookie` (the sliding-renewal decision).

See ``design/specs/091-web-api-auth/design.md`` (Architecture → Credential model, Architecture →
Cookie ``Secure`` flag) for the full mechanism this implements.
"""

import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
from contextlib import suppress
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path

from whenever import Instant

from hassette.config.models import WebApiConfig
from hassette.exceptions import AuthTokenWriteError, TrustedProxyConfigError

LOGGER = getLogger(__name__)

TOKEN_FILENAME = ".web_api_token"  # noqa: S105 — a filename, not a hardcoded credential
"""Name of the persisted token file, relative to ``data_dir``."""

TOKEN_BYTE_LENGTH = 32
"""Byte length passed to ``secrets.token_urlsafe()`` when generating a fresh token."""

SESSION_COOKIE_NAME = "hassette_session"
"""Name of the ``HttpOnly`` session cookie minted by ``POST /api/auth/session``."""

SESSION_ID_BYTE_LENGTH = 32
"""Byte length passed to ``secrets.token_urlsafe()`` for a session cookie's random session id."""

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


def _current_timestamp() -> int:
    """Current time as whole unix seconds.

    Extracted to a single call site so tests can patch ``hassette.web.auth._current_timestamp``
    directly for deterministic TTL/renewal-boundary assertions, instead of sleeping in real time.
    """
    return int(Instant.now().timestamp())


def check_bearer_token(presented: str | None, resolved_token: str | None) -> bool:
    """Timing-safe comparison of a presented bearer token against the resolved credential.

    A ``None`` ``resolved_token`` or ``presented`` value returns ``False`` directly, without
    reaching :func:`secrets.compare_digest` — that function raises ``TypeError`` on a ``None``
    argument, which would turn an intended 401 into an unhandled 500.
    ``WebApiConfig.auth_token`` can resolve to ``None`` even while ``auth_enabled=True`` in some
    test configurations, so this guard is on a real code path, not defensive padding.

    :func:`secrets.compare_digest` also raises ``TypeError`` when either ``str`` argument contains
    non-ASCII characters. ASGI servers decode HTTP header bytes via latin-1, so any byte >= 0x80 in
    a client-supplied ``Authorization`` header produces a non-ASCII ``presented`` value — reachable
    by any client, not a contrived edge case. That raise is caught here too, for the same reason:
    malformed input should degrade to "not authenticated," not surface as an unhandled 500.

    Args:
        presented: The token from the ``Authorization: Bearer <token>`` header, or ``None`` if
            absent.
        resolved_token: The web API's resolved credential (see :func:`resolve_auth_token`), or
            ``None``.

    Returns:
        ``True`` if both values are present and match; ``False`` otherwise.
    """
    if resolved_token is None or presented is None:
        return False
    try:
        return secrets.compare_digest(presented, resolved_token)
    except TypeError:
        return False


def _sign_session(resolved_token: str, session_id: str, issued_at: int) -> str:
    """Compute the HMAC-SHA256 hex digest binding ``session_id``/``issued_at`` to ``resolved_token``."""
    message = f"{session_id}.{issued_at}".encode()
    return hmac.new(resolved_token.encode(), message, hashlib.sha256).hexdigest()


def mint_session_cookie(resolved_token: str) -> str:
    """Mint a stateless session cookie value for ``resolved_token``.

    The value is HMAC-derived — keyed by ``resolved_token`` itself, so no new secret material is
    introduced — over a random session id plus the current time as the embedded issuance
    timestamp. Stateless: there is no server-side session table, so a minted cookie stays valid
    across ``WebApiService``'s ``RestartType.TRANSIENT`` restarts.

    Args:
        resolved_token: The web API's resolved bearer-token/session-cookie credential. Every call
            site mints only after a bearer-token check or a prior cookie verification has already
            confirmed a non-``None`` token, so this function does not itself guard against
            ``None`` — a ``None`` here would be a caller bug, not a request outcome to degrade
            gracefully for.

    Returns:
        The cookie value, shaped ``"<session_id>.<issued_at>.<hmac_hex>"``. Every component is
        drawn from a URL-safe/hex alphabet, so the value contains no dots, semicolons, or
        whitespace beyond the two literal separators — safe to place directly in a ``Set-Cookie``
        header.
    """
    session_id = secrets.token_urlsafe(SESSION_ID_BYTE_LENGTH)
    issued_at = _current_timestamp()
    signature = _sign_session(resolved_token, session_id, issued_at)
    return f"{session_id}.{issued_at}.{signature}"


def verify_session_cookie(cookie_value: str | None, resolved_token: str | None, session_ttl: int) -> int | None:
    """Verify a session cookie minted by :func:`mint_session_cookie`.

    Recomputes the HMAC over the cookie's embedded session id and issuance timestamp and compares
    it against the presented signature via :func:`secrets.compare_digest` (timing-safe), then
    separately checks the issuance timestamp against ``session_ttl``. ``session_ttl`` is read at
    verify time rather than baked into the cookie, so changing ``WebApiConfig.session_ttl`` takes
    effect for future verifications without needing to re-mint existing cookies.

    A ``None`` ``resolved_token`` or ``cookie_value``, a malformed cookie (wrong shape, a
    non-integer timestamp, non-ASCII characters in the signature segment), a signature mismatch,
    or an expired timestamp all return ``None`` — this function never raises for any of those;
    each is treated identically as "not authenticated". The non-ASCII case matters because ASGI
    servers decode HTTP header bytes via latin-1, so any byte >= 0x80 in a client-supplied
    ``Cookie`` header produces a non-ASCII ``signature`` segment, which would otherwise make
    :func:`secrets.compare_digest` raise ``TypeError`` and turn an intended 401 into an unhandled
    500.

    Args:
        cookie_value: The raw cookie value as sent by the client, or ``None`` if no cookie was
            presented.
        resolved_token: The web API's resolved credential, or ``None`` (never authenticates).
        session_ttl: Maximum age, in seconds, of a valid cookie (``WebApiConfig.session_ttl``).

    Returns:
        The cookie's embedded issuance timestamp (unix seconds) if the cookie is valid and
        unexpired; ``None`` otherwise.
    """
    if resolved_token is None or cookie_value is None:
        return None

    parts = cookie_value.split(".")
    if len(parts) != 3:
        return None

    session_id, issued_at_raw, signature = parts
    try:
        issued_at = int(issued_at_raw)
    except ValueError:
        return None

    expected_signature = _sign_session(resolved_token, session_id, issued_at)
    try:
        signature_valid = secrets.compare_digest(signature, expected_signature)
    except TypeError:
        return None
    if not signature_valid:
        return None

    if _current_timestamp() - issued_at > session_ttl:
        return None

    return issued_at


def should_set_secure_cookie_flag(
    client_address: str | None,
    forwarded_proto: str | None,
    trusted: TrustedProxySet,
) -> bool:
    """Decide whether a minted session cookie should carry the ``Secure`` flag.

    Calls :func:`is_trusted_peer` on the raw peer address first — the identical trusted-peer
    check the auth-bypass decision already performs, reused here rather than duplicated. Only
    when that peer is trusted does this function even look at ``forwarded_proto``; an untrusted
    peer's ``X-Forwarded-Proto`` is never consulted for anything, since it is a
    client-suppliable header value uvicorn never verifies.

    Args:
        client_address: The raw ASGI peer address (``scope["client"][0]`` /
            ``Request.client.host``), or ``None`` if unavailable.
        forwarded_proto: The request's ``X-Forwarded-Proto`` header value, or ``None`` if absent.
        trusted: The current resolved trusted-proxy set (see :func:`resolve_trusted_proxies`).

    Returns:
        ``True`` only when ``client_address`` matches ``trusted`` AND ``forwarded_proto`` is
        ``"https"`` (case-insensitive); ``False`` in every other case, including an untrusted
        peer regardless of ``forwarded_proto``'s value.
    """
    if client_address is None:
        return False
    if not is_trusted_peer(client_address, trusted):
        return False
    return forwarded_proto is not None and forwarded_proto.lower() == "https"


def should_renew_session_cookie(issued_at: int, session_ttl: int) -> bool:
    """Decide whether a verified session cookie should be replaced (sliding renewal).

    Takes the issuance timestamp returned by a prior successful :func:`verify_session_cookie`
    call rather than re-parsing the cookie value. This keeps the decision (this function) and the
    replacement value (:func:`mint_session_cookie`) separate from each other and from writing the
    ``Set-Cookie`` header, which is the response-handling middleware's job, not this
    module's.

    In the real request flow, a cookie already past the full ``session_ttl`` is rejected by
    :func:`verify_session_cookie` before this function is ever reached — this function's own
    upper bound is a second, independent guard for callers that hold an ``issued_at`` value
    without having just re-verified it, not the primary enforcement point for expiry.

    Args:
        issued_at: The cookie's embedded issuance timestamp (unix seconds), as returned by a
            successful :func:`verify_session_cookie` call.
        session_ttl: ``WebApiConfig.session_ttl``, in seconds.

    Returns:
        ``True`` once the cookie's age has reached or passed half of ``session_ttl`` and has not
        yet reached the full ``session_ttl``; ``False`` for a fresher cookie or one already past
        the full TTL (that case belongs to :func:`verify_session_cookie`'s rejection, not to
        renewal).
    """
    age = _current_timestamp() - issued_at
    return session_ttl / 2 <= age <= session_ttl
