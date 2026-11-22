"""WebSocket mechanics behind :meth:`~hassette_client.HassetteClient.listen`.

Hassette's ``/api/ws`` stream comes in; the caller's requested message types go out, and an exception when the
stream ends.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Collection, Mapping
from typing import Any, Literal, NoReturn, TypeVar, get_args, get_origin

import aiohttp
from hassette_wire import ConnectedWsMessage
from pydantic import BaseModel

from hassette_client.errors import (
    HassetteClientError,
    HassetteConnectionError,
    ResponseValidationError,
    error_class_for,
)
from hassette_client.parsing import parse_payload
from hassette_client.transport import RawResponse, Transport, http_error, log_raising, media_kind, parse_media_type

LOGGER = logging.getLogger(__name__)

WS_PATH = "/api/ws"
ENDPOINT = f"GET {WS_PATH}"

HEARTBEAT_SECONDS = 30.0
"""How often the stream sends a protocol ping; a missing pong ends it within about 1.5 intervals."""

CONNECTED_TYPE = "connected"
"""The ``type`` of the message the server sends first on every connection."""

MessageT = TypeVar("MessageT", bound=BaseModel)


async def listen(
    transport: Transport,
    on_message: Callable[[MessageT], Awaitable[None]],
    types: Collection[type[MessageT]],
    on_connected: Callable[[], Awaitable[None]] | None,
) -> NoReturn:
    """See :meth:`HassetteClient.listen <hassette_client.HassetteClient.listen>`."""
    by_tag = message_classes(types)
    try:
        async with asyncio.timeout(transport.request_timeout):
            ws = await transport.session.ws_connect(
                transport.base_url + WS_PATH, headers=transport.headers, heartbeat=HEARTBEAT_SECONDS
            )
    except aiohttp.WSServerHandshakeError as exc:
        raise log_raising(handshake_error(exc), cause=exc) from exc
    except (TimeoutError, aiohttp.ClientError) as exc:
        raise log_raising(transport.failure(exc, ENDPOINT), cause=exc) from exc

    async with ws:
        await wait_for_connected(transport, ws)
        LOGGER.debug("Stream from %s connected", transport.display_url)
        if on_connected is not None:
            await on_connected()
        while True:
            message = await receive(transport, ws)
            if message.type is aiohttp.WSMsgType.BINARY:
                LOGGER.debug("Skipping a binary frame from %s", transport.display_url)
                continue
            if message.type is not aiohttp.WSMsgType.TEXT:
                raise log_raising(stream_ended_error(transport, ws, message))
            tag = decode(message.data).get("type")
            message_class = by_tag.get(tag) if isinstance(tag, str) else None
            if message_class is None:
                LOGGER.debug("Skipping a %r message from %s", tag, transport.display_url)
                continue
            await on_message(parse_payload(message_class, message.data, endpoint=ENDPOINT))


def message_classes(types: Collection[type[MessageT]]) -> Mapping[str, type[MessageT]]:
    """Map each requested message class's ``type`` tag to the class.

    Raises:
        ValueError: A class has no single-value ``Literal`` ``type`` field, so it isn't a ``/ws`` message, or it is
            ``ConnectedWsMessage``, which ``on_connected`` stands in for.
    """
    by_tag: dict[str, type[MessageT]] = {}
    for message_class in types:
        field = message_class.model_fields.get("type")
        tags = get_args(field.annotation) if field is not None and get_origin(field.annotation) is Literal else ()
        if len(tags) != 1:
            raise ValueError(f"{message_class.__name__} is not a /ws message type")
        if message_class is ConnectedWsMessage:
            raise ValueError("ConnectedWsMessage can't be requested; pass on_connected instead")
        by_tag[tags[0]] = message_class
    return by_tag


async def wait_for_connected(transport: Transport, ws: aiohttp.ClientWebSocketResponse) -> None:
    """Read the server's first message and check it is ``connected``.

    Raises:
        HassetteTimeoutError: It didn't arrive within the transport's ``request_timeout``.
        HassetteConnectionError: The stream ended first, or the first message is something else.
    """
    try:
        async with asyncio.timeout(transport.request_timeout):
            message = await receive(transport, ws)
    except TimeoutError as exc:
        raise log_raising(transport.failure(exc, ENDPOINT), cause=exc) from exc
    if message.type is aiohttp.WSMsgType.BINARY:
        opened_with = "a binary frame"
    elif message.type is aiohttp.WSMsgType.TEXT:
        first_type = decode(message.data).get("type")
        if first_type == CONNECTED_TYPE:
            return
        opened_with = repr(first_type)
    else:
        raise log_raising(stream_ended_error(transport, ws, message))
    raise log_raising(
        HassetteConnectionError(
            f"The stream from {transport.display_url} opened with {opened_with} instead of {CONNECTED_TYPE!r}"
        )
    )


async def receive(transport: Transport, ws: aiohttp.ClientWebSocketResponse) -> aiohttp.WSMessage:
    """The next frame, with a connection error mapped to ``HassetteConnectionError``.

    ``ws.receive()`` turns most failures into a CLOSED or ERROR message, but its automatic reply to a server
    ping runs outside that handling, so a reset at that moment raises an ``aiohttp.ClientError`` instead.

    Raises:
        HassetteConnectionError: The connection failed while reading.
    """
    try:
        return await ws.receive()
    except aiohttp.ClientError as exc:
        error = HassetteConnectionError(f"The stream from {transport.display_url} ended ({type(exc).__name__})")
        raise log_raising(error, cause=exc) from exc


def decode(text: str) -> dict[str, Any]:
    """Decode one text frame as a JSON object.

    Raises:
        ResponseValidationError: The frame isn't a JSON object, so it didn't come from hassette.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        error = ResponseValidationError(
            model="a /ws message", endpoint=ENDPOINT, problems=["<body>: not a JSON object"]
        )
        raise log_raising(error)
    return data


def stream_ended_error(
    transport: Transport, ws: aiohttp.ClientWebSocketResponse, message: aiohttp.WSMessage
) -> HassetteConnectionError:
    """The exception for a stream that closed, failed, or lost its heartbeat.

    Names the error aiohttp recorded (such as the heartbeat's ``ServerTimeoutError``), else the close code.
    """
    cause = ws.exception()
    reason = type(cause).__name__ if cause is not None else f"close code {ws.close_code}"
    return HassetteConnectionError(f"The stream from {transport.display_url} ended ({message.type.name}, {reason})")


def handshake_error(exc: aiohttp.WSServerHandshakeError) -> HassetteClientError:
    """The exception for a handshake the server answered without upgrading.

    An error status maps through ``error_class_for`` as any HTTP failure does; the body isn't read, so the status
    alone picks the class. aiohttp follows redirects on a handshake, so a redirect is reported from its first hop.
    A 1xx or 2xx that didn't upgrade means something other than hassette answered.
    """
    first_hop = exc.history[0] if exc.history else None
    status = first_hop.status if first_hop is not None else exc.status
    if status < 300:
        return HassetteConnectionError(f"{ENDPOINT} didn't upgrade to a WebSocket: {exc.message} ({status})")
    headers = first_hop.headers if first_hop is not None else (exc.headers or {})
    media_type = parse_media_type(headers.get("Content-Type"))
    raw = RawResponse(
        status=status,
        media_type=media_type,
        kind=media_kind(media_type),
        payload=b"",
        truncated=False,
        location=headers.get("Location"),
    )
    return http_error(error_class_for(status, None), raw, ENDPOINT, problem=None)
