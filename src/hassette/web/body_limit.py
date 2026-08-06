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

from collections import deque
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

        buffered, oversized = await self._buffer_body(receive, scope)
        if oversized:
            await _send_413(send, self.max_bytes)
            return

        await self.app(scope, _replay_receive(buffered, receive), send)

    async def _buffer_body(self, receive: Receive, scope: Scope) -> tuple[list[Message], bool]:
        """Drain the request body into memory, stopping early once it exceeds ``max_bytes``.

        Deciding pass/reject here — before ``self.app`` (``DefaultDenyMiddleware`` and, beneath
        it, FastAPI's routing) ever runs — is what makes the 413 reachable for a streamed body
        with no ``Content-Length``. The previous approach raised a private exception out of a
        wrapped ``receive`` for the app to unwind through, but FastAPI's own body parsing wraps
        ``await request.json()`` in a broad ``except Exception`` and converts anything raised
        there — including our exception — into its own generic
        ``400 {"detail": "There was an error parsing the body"}``, silently losing both the 413
        and the ``X-Max-Body-Bytes`` header. Buffering ourselves sidesteps that entirely: nothing
        downstream gets a chance to intercept the decision.

        Returns the buffered ASGI messages read so far, and whether the body exceeded
        ``max_bytes`` (``True`` means the caller must answer 413 and must not invoke
        ``self.app`` — the buffered messages are partial and not meant to be replayed).
        """
        buffered: list[Message] = []
        received = 0

        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":
                # e.g. http.disconnect — the client is gone, nothing left to read.
                return buffered, False

            received += len(message.get("body", b""))
            if received > self.max_bytes:
                LOGGER.warning(
                    "Rejecting %s %s: body exceeded the %d-byte ceiling after %d bytes",
                    scope.get("method", "?"),
                    scope.get("path", "?"),
                    self.max_bytes,
                    received,
                )
                return buffered, True

            if not message.get("more_body", False):
                return buffered, False


def _replay_receive(buffered: list[Message], receive: Receive) -> Receive:
    """Build a ``receive`` that first drains ``buffered``, then falls through to the real one.

    The fallthrough matters: once the buffered body is exhausted, the downstream app may still
    legitimately call ``receive()`` again (e.g. to observe a later ``http.disconnect``).
    """
    queue = deque(buffered)

    async def _receive() -> Message:
        if queue:
            return queue.popleft()
        return await receive()

    return _receive
