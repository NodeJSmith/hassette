"""Default-deny ASGI middleware for the Hassette Web API.

A single :class:`DefaultDenyMiddleware` gates every route under the ``/api/`` prefix. It delegates
the auth decision itself to :func:`~hassette.web.auth.resolve_auth_outcome`, shared with
:func:`~hassette.web.auth.authorize_ws` so the HTTP and WebSocket halves of the gate cannot drift:
a presented ``Authorization`` header is validated and fails closed, and trusted-peer match
(:func:`~hassette.web.auth.is_trusted_peer`) then session cookie
(:func:`~hassette.web.auth.verify_session_cookie`) apply only when no header was presented.

Three routes bypass the auth decision entirely: ``GET /api/health/live``,
``GET /api/health/ready``, and ``POST /api/auth/session``. Two response-side behaviors apply
regardless of which branch let a request through: sliding session-cookie renewal and coalesced
failed-auth counting — this is why the middleware is a
:class:`~starlette.middleware.base.BaseHTTPMiddleware` rather than a raw ASGI middleware, per
design.md's Architecture → Middleware and routing.

See ``design/specs/091-web-api-auth/design.md`` (Architecture → Middleware and routing) for the
full mechanism this implements.
"""

import time
from collections import OrderedDict
from logging import getLogger

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from hassette.web.auth import (
    SESSION_COOKIE_NAME,
    get_trusted_proxies,
    mint_session_cookie,
    peer_address,
    peer_address_or_unknown,
    resolve_auth_outcome,
    should_renew_session_cookie,
    should_set_secure_cookie_flag,
)

LOGGER = getLogger(__name__)

GATED_PREFIX = "/api/"
"""Only requests whose path starts with this prefix are subject to default-deny.

Everything else — the SPA shell, ``/assets``, ``/fonts`` — is served by the same app but stays
reachable with no credential, because the login view lives in that bundle. See design.md's
Architecture → Middleware and routing for why this is load-bearing, not an optimization.
"""

EXEMPT_ROUTES = frozenset(
    {
        ("GET", "/api/health/live"),
        ("GET", "/api/health/ready"),
        ("POST", "/api/auth/session"),
    }
)
"""The only three routes that bypass the trusted-peer/bearer/cookie checks entirely.

Deliberately excludes ``/api/docs`` and ``/api/openapi.json`` — see design.md Edge Cases, closing
the previously-unauthenticated API-schema fingerprinting surface.
"""

FAILED_AUTH_THRESHOLD = 10
"""Number of failed-auth (401) responses from one source within the window that triggers one
coalesced WARN. A deliberate, rounder choice in the ballpark of design.md's own illustrative
"12 failed auth attempts... in the last 5 minutes" example — design.md phrases that figure as an
"e.g.", not a pinned requirement."""

FAILED_AUTH_WINDOW_SECONDS = 300
"""Sliding window, in seconds, over which :data:`FAILED_AUTH_THRESHOLD` is evaluated (5 minutes)."""

MAX_TRACKED_SOURCES = 1024
"""Upper bound on distinct source addresses held by :class:`_FailedAuthTracker` at once.

The tracker is a logging aid, not a control (rate limiting is an explicit Non-Goal — see
design.md Non-Goals), so discarding the least-recently-touched source under pressure is
preferable to unbounded growth driven by an unauthenticated peer that varies its source address
across requests (e.g. sweeping an IPv6 /64).
"""


class _FailedAuthTracker:
    """Coalesced failed-auth counter, keyed by source peer address.

    Evicts attempts older than :data:`FAILED_AUTH_WINDOW_SECONDS` on every :meth:`record` call and
    drops a source's key entirely once its window has fully elapsed, so a sustained burst cannot
    grow the tracker without bound — across sources as well as within one, since the number of
    distinct sources held at once is additionally capped at :data:`MAX_TRACKED_SOURCES` via
    least-recently-touched eviction. Emits exactly one WARN the moment a source's attempt count
    *reaches* the threshold within the window — not one per attempt, and not a repeat warning for
    every attempt past the threshold. The counter never rejects or throttles anything; rate
    limiting is an explicit Non-Goal (design.md Non-Goals).
    """

    def __init__(self) -> None:
        self._attempts: OrderedDict[str, list[float]] = OrderedDict()

    def record(self, source: str) -> None:
        now = time.monotonic()
        window_start = now - FAILED_AUTH_WINDOW_SECONDS
        attempts = [t for t in self._attempts.get(source, ()) if t >= window_start]
        attempts.append(now)
        self._attempts[source] = attempts
        self._attempts.move_to_end(source)

        # Drop any other source whose most recent attempt has aged out of the window, then cap
        # what remains so an attacker who varies the source address per request can't grow this
        # dict without bound.
        stale = [key for key, times in self._attempts.items() if key != source and times[-1] < window_start]
        for key in stale:
            del self._attempts[key]
        while len(self._attempts) > MAX_TRACKED_SOURCES:
            self._attempts.popitem(last=False)

        if len(attempts) == FAILED_AUTH_THRESHOLD:
            LOGGER.warning(
                "%d failed auth attempts from %s in the last %d seconds",
                FAILED_AUTH_THRESHOLD,
                source,
                FAILED_AUTH_WINDOW_SECONDS,
            )


def _unauthorized_response() -> JSONResponse:
    return JSONResponse({"detail": "Not authenticated"}, status_code=401)


def _source_key(request: Request) -> str:
    """Identify the failed-auth counter's "source" for a request — the raw peer address.

    Falls back to a fixed placeholder when the ASGI transport reports no client (e.g. some test
    transports) so the tracker still has a stable key to coalesce against, rather than treating
    every such request as a distinct source.
    """
    return peer_address_or_unknown(request)


class DefaultDenyMiddleware(BaseHTTPMiddleware):
    """Default-deny gate for every route under :data:`GATED_PREFIX`.

    See the module docstring and design.md's Architecture → Middleware and routing for the full
    mechanism. Registered in ``web/app.py`` — see that module for the registration-order rationale
    (CORS must be the outermost layer).
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._failed_auth = _FailedAuthTracker()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith(GATED_PREFIX):
            return await call_next(request)

        hassette = request.app.state.hassette
        web_api_config = hassette.config.web_api

        # Auth disabled: let everything through unconditionally, no side effects at all. This is
        # what keeps create_hassette_stub(auth_enabled=False) (the default) passing the existing
        # integration/e2e suites unchanged.
        if not web_api_config.auth_enabled:
            return await call_next(request)

        route_key = (request.method, request.url.path)
        if route_key in EXEMPT_ROUTES:
            # The trusted-peer/bearer/cookie checks are bypassed entirely for these three routes —
            # they're reachable with zero prior credential. Sliding renewal and failed-auth
            # counting still apply below: no renewal (the middleware never authenticated this
            # request via a cookie, so there's nothing to renew), but failed-auth counting still
            # applies to the outgoing status — this is what makes POST /api/auth/session's own
            # handler-issued 401 countable.
            response = await call_next(request)
            if response.status_code == 401:
                self._failed_auth.record(_source_key(request))
            return response

        trusted_proxies = get_trusted_proxies(request.app.state)
        resolved_token = getattr(request.app.state, "auth_token", None)

        outcome = resolve_auth_outcome(request, trusted_proxies, resolved_token, web_api_config.session_ttl)

        if not outcome.authenticated:
            self._failed_auth.record(_source_key(request))
            return _unauthorized_response()

        response = await call_next(request)

        # Sliding renewal — only for a request authenticated via session cookie.
        if outcome.session_issued_at is not None and resolved_token is not None:
            if should_renew_session_cookie(outcome.session_issued_at, web_api_config.session_ttl):
                new_cookie_value = mint_session_cookie(resolved_token)
                # A second, independent read of the peer address: resolve_auth_outcome consulted it
                # to decide auth, this one decides the cookie's Secure flag. Same value, different
                # question — see should_set_secure_cookie_flag on why the two share one signal.
                secure = should_set_secure_cookie_flag(
                    peer_address(request), request.headers.get("x-forwarded-proto"), trusted_proxies
                )
                response.set_cookie(
                    SESSION_COOKIE_NAME,
                    new_cookie_value,
                    max_age=web_api_config.session_ttl,
                    httponly=True,
                    samesite="strict",
                    secure=secure,
                )

        # Failed-auth counting keys off the outgoing status, not off this middleware's own reject
        # branch (that path already returned above) — a route the middleware let through can still
        # have its own handler issue a 401.
        if response.status_code == 401:
            self._failed_auth.record(_source_key(request))

        return response
