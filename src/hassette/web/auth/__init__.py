"""Default-deny authentication gate for the web API.

Composes the three independent auth pieces into the one precedence decision both halves of the
gate use — the HTTP middleware and the WebSocket handshake:

- :mod:`hassette.web.auth.tokens` — bearer-token/session-cookie credential resolution.
- :mod:`hassette.web.auth.trusted_proxies` — ``trusted_proxies`` peer matching.
- :mod:`hassette.web.auth.session` — bearer-token/session-cookie auth primitives.

:func:`resolve_auth_outcome` is the composition: a presented ``Authorization`` header is
authoritative and fails closed on any invalid form; peer trust and the session cookie apply only
to a caller that presents no header at all. See ``design/specs/091-web-api-auth/design.md``
(Architecture → Credential model, Architecture → Cookie ``Secure`` flag) for the full mechanism
this implements.
"""

from dataclasses import dataclass

from starlette.requests import HTTPConnection
from starlette.websockets import WebSocket

from hassette.web.auth.session import (
    SESSION_COOKIE_NAME,
    check_bearer_token,
    extract_bearer_token,
    verify_session_cookie,
)
from hassette.web.auth.trusted_proxies import TrustedProxySet, get_trusted_proxies, is_trusted_peer, peer_address

WS_POLICY_VIOLATION_CLOSE_CODE = 1008
"""WebSocket close code for a policy violation (RFC 6455 §7.4.1) — used for an unauthorized
pre-``accept()`` rejection. See :func:`authorize_ws` and design.md's WebSocket auth section for why
this code is not literally observed by the client on this project's uvicorn backend."""


@dataclass(frozen=True)
class AuthOutcome:
    """The result of :func:`resolve_auth_outcome`: whether the caller is in, and how.

    Attributes:
        authenticated: Whether the request or handshake may proceed.
        session_issued_at: The issuance timestamp of the session cookie that authenticated this
            request, or ``None`` when some other mechanism did. Only a cookie-authenticated
            request is a candidate for sliding renewal, so this is what
            :class:`~hassette.web.middleware.DefaultDenyMiddleware` keys that decision off.
    """

    authenticated: bool
    session_issued_at: int | None = None


def resolve_auth_outcome(
    connection: HTTPConnection,
    trusted: TrustedProxySet,
    resolved_token: str | None,
    session_ttl: int,
) -> AuthOutcome:
    """Decide whether ``connection`` is authenticated, and by which mechanism.

    The single precedence decision behind both halves of the default-deny gate:
    :class:`~hassette.web.middleware.DefaultDenyMiddleware` for HTTP and :func:`authorize_ws` for
    the WebSocket handshake. ``BaseHTTPMiddleware`` only ever sees ``http``-scope requests and
    never runs for a WebSocket upgrade, so without one shared function the two would each carry
    their own copy of this ordering and could drift apart — this is the "same validator used by the
    HTTP middleware" property design.md's WebSocket auth section requires.

    **A presented credential is authoritative.** When an ``Authorization`` header is present at
    all, the bearer token decides the outcome on its own: a wrong token, an unrecognized scheme,
    and an empty value all fail closed, with no fall-through to peer trust or to a session cookie.
    Failing closed on a *malformed* header, not only a wrong one, is deliberate — a surprising 401
    to a misconfigured client beats a bypass a trusted peer could exploit, and the caller who sent
    the bad header is the one who can see the failure.

    **Ambient peer trust covers only callers presenting nothing.** With no ``Authorization``
    header, :func:`~hassette.web.auth.trusted_proxies.is_trusted_peer` runs first and the session
    cookie second. This is what lets one host serve both mechanisms at once: a browser behind a
    forward-auth proxy sends no ``Authorization`` header and is admitted by peer match with no
    Hassette login, while the CLI presents a bearer token that Hassette validates itself.

    Args:
        connection: The incoming request or WebSocket. Only its peer address, headers, and cookies
            are read — never a client-suppliable forwarding header (see
            :func:`~hassette.web.auth.trusted_proxies.is_trusted_peer`).
        trusted: The current resolved trusted-proxy set.
        resolved_token: The web API's resolved credential, or ``None`` (never authenticates
            anything, but does not change the precedence above).
        session_ttl: ``WebApiConfig.session_ttl``, in seconds.

    Returns:
        The :class:`AuthOutcome`. Never raises — every malformed input degrades to "not
        authenticated" (see :func:`~hassette.web.auth.session.check_bearer_token` and
        :func:`~hassette.web.auth.session.verify_session_cookie`).
    """
    # Header *presence*, not token validity, is what diverts away from the fallbacks below.
    # `extract_bearer_token` returns None for a missing header and for a malformed one alike, so
    # swapping this for `extract_bearer_token(...) is not None` would send exactly the malformed
    # cases back down to peer trust — reintroducing the bypass this ordering exists to close.
    if "authorization" in connection.headers:
        presented_token = extract_bearer_token(connection.headers)
        if check_bearer_token(presented_token, resolved_token):
            return AuthOutcome(authenticated=True)
        return AuthOutcome(authenticated=False)

    client_address = peer_address(connection)
    if client_address is not None and is_trusted_peer(client_address, trusted):
        return AuthOutcome(authenticated=True)

    cookie_value = connection.cookies.get(SESSION_COOKIE_NAME)
    issued_at = verify_session_cookie(cookie_value, resolved_token, session_ttl)
    if issued_at is not None:
        return AuthOutcome(authenticated=True, session_issued_at=issued_at)

    return AuthOutcome(authenticated=False)


def authorize_ws(websocket: WebSocket) -> bool:
    """Authorization check for the WebSocket handshake.

    The WebSocket half of the default-deny gate. Delegates the precedence decision to
    :func:`resolve_auth_outcome` — the same function
    :class:`~hassette.web.middleware.DefaultDenyMiddleware` calls for HTTP requests — and discards
    the sliding-renewal timestamp, which has no analogue for a handshake.

    Includes the same ``auth_enabled`` bypass (step 0) as the HTTP middleware, for the same
    reason: ``create_hassette_stub(auth_enabled=False)`` (the default) must keep every existing WS
    test passing unchanged.

    Reads the resolved credential from ``websocket.app.state.auth_token`` and the resolved
    trusted-proxy set from ``websocket.app.state.trusted_proxies`` — both set by
    :func:`hassette.web.app.create_fastapi_app` as siblings to the existing
    ``websocket.app.state.hassette`` (the same accessor pattern ``web/routes/ws.py`` already uses)
    — never from ``websocket.app.state.hassette.config.web_api``, which only ever holds the raw,
    possibly-unresolved operator-configured values.

    Non-browser clients (CLI, scripts) attach ``Authorization: Bearer <token>`` via the
    ``websockets`` library's ``additional_headers`` parameter at connect time, so the
    presented-credential precedence :func:`resolve_auth_outcome` documents applies here in full,
    not only on the HTTP paths.

    Args:
        websocket: The incoming WebSocket connection, checked before ``accept()`` is called.

    Returns:
        ``True`` if the connection should be accepted; ``False`` if it should be closed with code
        :data:`WS_POLICY_VIOLATION_CLOSE_CODE` instead of being accepted.
    """
    hassette = websocket.app.state.hassette
    web_api_config = hassette.config.web_api

    if not web_api_config.auth_enabled:
        return True

    outcome = resolve_auth_outcome(
        websocket,
        get_trusted_proxies(websocket.app.state),
        getattr(websocket.app.state, "auth_token", None),
        web_api_config.session_ttl,
    )
    return outcome.authenticated
