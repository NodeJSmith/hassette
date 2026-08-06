"""Request-body size ceiling for the Hassette Web API.

Uvicorn has no maximum-body-size setting and Starlette buffers a whole body before a handler
sees it, so without this middleware the one credential-free JSON route
(``POST /api/auth/session`` — see ``web/middleware.py``'s ``EXEMPT_ROUTES``) performs
attacker-controlled allocation before any token comparison happens. An 8 MiB token was verified
to reach the handler and return its normal 401.

This is a raw ASGI middleware rather than a
:class:`~starlette.middleware.base.BaseHTTPMiddleware` on purpose: it has to wrap ``receive`` to
count body bytes as they arrive. A ``Content-Length`` check alone is not a limit, because a
client that omits it and uses ``Transfer-Encoding: chunked`` would stream past the ceiling
unmeasured.

The limit is a module constant, not a config field. Every body-carrying route in the API takes a
small fixed payload — a log level, an app key, a job trigger — so there is no legitimate reason
for a deployment to raise it, and a knob in ``web_api`` config would surface in the config UI and
the OpenAPI schema for no one's benefit.
"""

from logging import getLogger

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOGGER = getLogger(__name__)

MAX_REQUEST_BODY_BYTES = 64 * 1024
"""Ceiling on a single request body, in bytes.

The largest body any route legitimately accepts is a session-token exchange, whose token is itself
capped at ``MAX_SESSION_TOKEN_LENGTH`` (4096) — so 64 KiB leaves roughly 16x headroom over the
worst legitimate case and about 1500x over a generated 43-character token. Small enough that the
pre-authentication allocation on ``POST /api/auth/session`` cannot become memory pressure, loose
enough that no real request comes close.
"""


class _BodyTooLargeError(Exception):
    """Raised out of the wrapped ``receive`` once a body exceeds the ceiling.

    Private and never allowed to escape :class:`RequestBodySizeLimitMiddleware.__call__` — it
    exists only to unwind out of whatever handler was awaiting the body, so the middleware can
    answer 413 in its place.

    The unwind crosses a middleware boundary, which is worth knowing before editing the stack:
    the app this middleware wraps is ``DefaultDenyMiddleware``, a Starlette
    :class:`~starlette.middleware.base.BaseHTTPMiddleware`, which runs the downstream app in its
    own task and re-raises that task's exception on the caller's side. So a raise inside
    ``receive`` does reach the ``except`` in ``__call__`` rather than vanishing into a task — but
    that is a property of the wrapped stack, not a guarantee of the ASGI spec. The 413 tests in
    ``tests/integration/web_api/test_body_limit.py`` cover both the in-process transport and a real
    uvicorn server precisely so a reordering that broke this propagation would fail loudly.
    """


def _declared_content_length(headers: Headers) -> int | None:
    """Return the request's declared ``Content-Length``, or None when absent or unparseable.

    A malformed value is treated as absent rather than as a rejection: the byte counter below is
    the authoritative check, and letting the server's own protocol handling reject a bad header
    keeps this middleware from having an opinion about framing.
    """
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def _send_413(send: Send, max_bytes: int) -> None:
    body = b'{"detail":"Request body too large"}'
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                # Advertise the ceiling so a client gets an actionable answer rather than
                # having to bisect payload sizes against an opaque 413.
                (b"x-max-body-bytes", str(max_bytes).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestBodySizeLimitMiddleware:
    """Reject any HTTP request whose body exceeds ``max_bytes`` with a 413.

    Registered outside :class:`~hassette.web.middleware.DefaultDenyMiddleware` (see
    ``web/app.py``) so an oversized body is refused before the auth decision runs, on every
    route rather than only the gated ones.

    Non-HTTP scopes — the WebSocket handshake at ``/api/ws``, plus ``lifespan`` — pass straight
    through. WebSocket frame limits are the transport's concern, not this middleware's.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = _declared_content_length(headers)
        if declared is not None and declared > self.max_bytes:
            # Reject on the declaration alone: no body bytes need to be read at all, so an
            # honest client that announces an oversized payload costs nothing.
            LOGGER.warning(
                "Rejecting %s %s: declared Content-Length %d exceeds the %d-byte ceiling",
                scope.get("method", "?"),
                scope.get("path", "?"),
                declared,
                self.max_bytes,
            )
            await _send_413(send, self.max_bytes)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    LOGGER.warning(
                        "Rejecting %s %s: body exceeded the %d-byte ceiling after %d bytes",
                        scope.get("method", "?"),
                        scope.get("path", "?"),
                        self.max_bytes,
                        received,
                    )
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLargeError:
            # Only safe to answer 413 if the app hadn't already started a response. A handler that
            # streamed a status line before reading its body has committed the response, and a
            # second http.response.start would be an ASGI violation. Re-raising instead hands the
            # exception to the server's own error handling, which — with headers already sent —
            # can only abort the connection mid-response, leaving the client with a truncated
            # read. No route in this app streams a response before reading its body, so this
            # branch is unreachable today; it exists so adding one degrades to a broken
            # connection rather than to a protocol violation.
            if not response_started:
                await _send_413(send, self.max_bytes)
                return
            raise
