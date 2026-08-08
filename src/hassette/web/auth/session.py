"""Bearer-token/session-cookie authentication primitives for the web API.

:func:`check_bearer_token` (timing-safe comparison), :func:`mint_session_cookie`/
:func:`verify_session_cookie` (stateless, HMAC-derived cookie keyed by the resolved token),
:func:`should_set_secure_cookie_flag` (reuses :func:`~hassette.web.auth.trusted_proxies.is_trusted_peer`
to decide the cookie's ``Secure`` attribute), and :func:`should_renew_session_cookie` (the
sliding-renewal decision). See ``design/specs/091-web-api-auth/design.md`` (Architecture → Cookie
``Secure`` flag) for the full mechanism this implements.
"""

import hashlib
import hmac
import secrets

from starlette.datastructures import Headers
from whenever import Instant

from hassette.web.auth.trusted_proxies import TrustedProxySet, is_trusted_peer

SESSION_COOKIE_NAME = "hassette_session"
"""Name of the ``HttpOnly`` session cookie minted by ``POST /api/auth/session``."""

SESSION_ID_BYTE_LENGTH = 32
"""Byte length passed to ``secrets.token_urlsafe()`` for a session cookie's random session id."""

COOKIE_SEGMENT_COUNT = 3
"""Number of dot-separated segments in a valid session cookie value: ``session_id.issued_at.signature``."""


def _current_timestamp() -> int:
    """Current time as whole unix seconds.

    Extracted to a single call site so tests can patch ``hassette.web.auth.session._current_timestamp``
    directly for deterministic TTL/renewal-boundary assertions, instead of sleeping in real time.
    """
    return int(Instant.now().timestamp())


def extract_bearer_token(headers: Headers) -> str | None:
    """Parse an ``Authorization: Bearer <token>`` header out of ``headers``.

    Shared by :class:`~hassette.web.middleware.DefaultDenyMiddleware` (via
    ``request.headers``) and :func:`~hassette.web.auth.authorize_ws` (via ``websocket.headers``) — both
    ``Request.headers`` and ``WebSocket.headers`` are the same Starlette
    :class:`~starlette.datastructures.Headers` type, so one parser serves both call sites.

    Args:
        headers: The incoming request's or WebSocket's headers.

    Returns:
        The token value if the ``Authorization`` header is present and shaped
        ``"Bearer <token>"`` with a non-empty token; ``None`` if the header is absent, uses a
        different scheme, or the token portion is empty.
    """
    header = headers.get("authorization")
    if header is None:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value


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
        resolved_token: The web API's resolved credential (see
            :func:`~hassette.web.auth.tokens.resolve_auth_token`), or ``None``.

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
    if len(parts) != COOKIE_SEGMENT_COUNT:
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

    Calls :func:`~hassette.web.auth.trusted_proxies.is_trusted_peer` on the raw peer address first —
    the identical trusted-peer check the auth-bypass decision already performs, reused here rather
    than duplicated. Only when that peer is trusted does this function even look at
    ``forwarded_proto``; an untrusted peer's ``X-Forwarded-Proto`` is never consulted for anything,
    since it is a client-suppliable header value uvicorn never verifies.

    Args:
        client_address: The raw ASGI peer address (``scope["client"][0]`` /
            ``Request.client.host``), or ``None`` if unavailable.
        forwarded_proto: The request's ``X-Forwarded-Proto`` header value, or ``None`` if absent.
        trusted: The current resolved trusted-proxy set (see
            :func:`~hassette.web.auth.trusted_proxies.resolve_trusted_proxies`).

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
