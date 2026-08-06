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
from collections import OrderedDict, deque
from dataclasses import dataclass, field
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


@dataclass
class _SourceAttempts:
    """Bounded record of one source's recent failed-auth attempts.

    ``timestamps`` is a ring buffer capped at :data:`FAILED_AUTH_THRESHOLD` entries. The tracker
    only ever asks "did the last ``FAILED_AUTH_THRESHOLD`` attempts all land inside the window?",
    so a timestamp older than that is unreachable by any question the tracker can pose and the
    deque drops it for free. This cap is what keeps both retained memory and per-request work
    constant for a source under sustained load — an unbounded list makes each
    :meth:`_FailedAuthTracker.record` O(attempts so far) and a burst O(n^2) overall, which one
    unauthenticated peer can aim at the shared event loop.

    Mutated in place rather than replaced. The whole point of a fixed-size ring buffer is to avoid
    the per-request copy, so the usual copy-on-write preference is inverted here deliberately.
    """

    timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=FAILED_AUTH_THRESHOLD))
    warned: bool = False
    """Whether the WARN has already fired for the burst currently in progress.

    Re-armed as soon as the in-window count falls back below the threshold, so a peer that goes
    quiet and later resumes gets a fresh warning rather than permanent silence. See
    :meth:`_FailedAuthTracker.record` for where the re-arm check actually happens — it must run
    before the current attempt is appended, not after.
    """


class _FailedAuthTracker:
    """Coalesced failed-auth counter, keyed by source peer address.

    Bounded on both axes an unauthenticated peer controls:

    - **Across sources** — the number of distinct addresses held at once is capped at
      :data:`MAX_TRACKED_SOURCES` via least-recently-touched eviction, and any source whose most
      recent attempt has aged out of the window is dropped entirely. A peer varying its address
      per request (cheap over an IPv6 /64) cannot grow the dict without bound.
    - **Within one source** — see :class:`_SourceAttempts`. Constant memory and constant work per
      request regardless of how many attempts that source has already made.

    Emits exactly one WARN the moment a source's in-window attempt count *reaches* the threshold —
    not one per attempt, and not a repeat for every attempt past it. The counter never rejects or
    throttles anything; rate limiting is an explicit Non-Goal (design.md Non-Goals).
    """

    def __init__(self) -> None:
        self._attempts: OrderedDict[str, _SourceAttempts] = OrderedDict()

    def record(self, source: str) -> None:
        now = time.monotonic()
        window_start = now - FAILED_AUTH_WINDOW_SECONDS

        state = self._evict_stale_attempts(source, window_start)

        # Re-arm while the *pre-attempt* survivor count is still below threshold — this must
        # happen before the append below. ``timestamps`` is a ``maxlen``-bounded deque, so once a
        # source has ever made FAILED_AUTH_THRESHOLD attempts, its length pins at exactly that
        # value after every future append. Checking post-append length can therefore never observe
        # a dip below threshold; it would only ever see 0 survivors (full staleness) or the cap.
        if len(state.timestamps) < FAILED_AUTH_THRESHOLD:
            state.warned = False

        state.timestamps.append(now)
        self._enforce_source_bounds(window_start)

        if len(state.timestamps) >= FAILED_AUTH_THRESHOLD and not state.warned:
            state.warned = True
            LOGGER.warning(
                "%d failed auth attempts from %s in the last %d seconds",
                FAILED_AUTH_THRESHOLD,
                source,
                FAILED_AUTH_WINDOW_SECONDS,
            )

    def _evict_stale_attempts(self, source: str, window_start: float) -> _SourceAttempts:
        """Return ``source``'s state with attempts older than ``window_start`` dropped.

        Also moves ``source`` to the end of ``_attempts``, which is what makes the dict
        LRU-ordered. :meth:`_evict_stale_sources` depends on that ordering — do not drop the
        ``move_to_end`` call without reading its docstring first.

        Deliberately does not append the new attempt — the caller needs the survivor count in
        this pre-append state to decide whether to re-arm the warning latch.
        """
        state = self._attempts.get(source)
        if state is None:
            state = _SourceAttempts()
            self._attempts[source] = state  # a fresh key lands at the end already
        else:
            self._attempts.move_to_end(source)

        # Drop attempts that have aged out of the window. This is a *time* bound and is separate
        # from the deque's own maxlen, which is a *count* bound — the deque cannot know that an
        # entry it still has room for is too old to count toward the threshold.
        while state.timestamps and state.timestamps[0] < window_start:
            state.timestamps.popleft()
        return state

    def _enforce_source_bounds(self, window_start: float) -> None:
        """Keep the number of tracked sources bounded: drop aged-out ones, then cap the rest."""
        self._evict_stale_sources(window_start)
        while len(self._attempts) > MAX_TRACKED_SOURCES:
            self._attempts.popitem(last=False)

    def _evict_stale_sources(self, window_start: float) -> None:
        """Drop every source whose most recent attempt has aged out of the window.

        The dict is LRU-ordered — :meth:`record` moves each touched source to the end — so stale
        sources cluster at the front and the scan can stop at the first live one. That makes this
        O(1) amortized instead of the full walk of up to :data:`MAX_TRACKED_SOURCES` entries that
        a per-request comprehension over the whole dict would cost.

        The just-touched source is safe: it sits at the end with a timestamp of ``now``, so the
        loop stops before reaching it (and stops immediately when it is the only entry).
        """
        while self._attempts:
            oldest = next(iter(self._attempts))
            state = self._attempts[oldest]
            if state.timestamps and state.timestamps[-1] >= window_start:
                return
            del self._attempts[oldest]


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
