"""``HassetteClient.listen``: connecting, filtering by type, ordering, and how a stream ends (spec 159 D5-D9)."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from fake_server import TEST_TOKEN
from hassette_client import (
    AuthenticationError,
    ForbiddenError,
    HassetteClient,
    HassetteConnectionError,
    HassetteTimeoutError,
    RedirectError,
    ResponseValidationError,
)
from hassette_client import stream as stream_module
from hassette_wire import (
    AppStatusChangedWsMessage,
    ConnectedData,
    ConnectedWsMessage,
    EntityStateChangedWsMessage,
)

CONNECTED = {"type": "connected", "data": {"uptime_seconds": 1.0, "entity_count": 0, "app_count": 1}, "timestamp": 1.0}

STATUS_MESSAGE = {
    "type": "app_status_changed",
    "data": {"app_key": "my_app", "instance_name": "kitchen", "status": "running"},
    "timestamp": 3.0,
}


def entity_message(revision: int, value: Any = 1.5) -> dict[str, Any]:
    entity = {"key": "temp", "platform": "sensor", "name": "Temp", "value": value, "attributes": {}}
    data = {"boot_id": "b1", "revision": revision, "app_key": "my_app", "instance_name": "kitchen", "entity": entity}
    return {"type": "entity_state_changed", "data": data, "timestamp": 2.0}


@dataclass
class FakeWsServer:
    """Sends ``frames`` to each connection, then closes it; with ``hold``, keeps it open until the client closes."""

    base_url: str = ""
    frames: list[Any] = field(default_factory=list)
    hold: bool = False
    autoping: bool = True
    status: int | None = None
    """Answer the handshake with this HTTP status instead of upgrading."""
    headers: dict[str, str] = field(default_factory=dict)
    handshake_headers: list[dict[str, str]] = field(default_factory=list)
    client_closed: asyncio.Event = field(default_factory=asyncio.Event)
    """Set when the client closes a held connection."""

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.handshake_headers.append(dict(request.headers))
        if self.status is not None:
            return web.Response(status=self.status, headers=self.headers)
        ws = web.WebSocketResponse(autoping=self.autoping)
        await ws.prepare(request)
        for frame in self.frames:
            await (ws.send_bytes(frame) if isinstance(frame, bytes) else ws.send_str(json.dumps(frame)))
        if self.hold:
            async for _ in ws:
                pass
            self.client_closed.set()
        await ws.close()
        return ws


async def login_page(_: web.Request) -> web.Response:
    return web.Response(text="login page")


@pytest.fixture
async def ws_server() -> AsyncIterator[FakeWsServer]:
    fake = FakeWsServer()
    app = web.Application()
    app.router.add_get("/api/ws", fake.handle)
    app.router.add_get("/elsewhere", login_page)
    async with TestServer(app) as test_server:
        fake.base_url = str(test_server.make_url("")).rstrip("/")
        yield fake


@pytest.fixture
def ws_client(session: aiohttp.ClientSession, ws_server: FakeWsServer) -> HassetteClient:
    return HassetteClient(session, ws_server.base_url, token=TEST_TOKEN, request_timeout=2)


class Recorder:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def on_message(self, message: Any) -> None:
        self.events.append(message)

    async def on_connected(self) -> None:
        self.events.append("connected")


async def test_passes_requested_types_in_order_after_on_connected(
    ws_client: HassetteClient, ws_server: FakeWsServer
) -> None:
    ws_server.frames = [
        CONNECTED,
        entity_message(5),
        {"type": "log_hint", "timestamp": 1.0},
        {"type": "from_the_future", "data": "not even an object"},
        {"type": ["not", "a", "tag"]},
        b"binary",
        STATUS_MESSAGE,
        entity_message(6, value=2.5),
    ]
    recorder = Recorder()

    # The fake server closes after its frames, which ends the stream.
    with pytest.raises(HassetteConnectionError, match="ended"):
        await ws_client.listen(
            recorder.on_message,
            types=(EntityStateChangedWsMessage, AppStatusChangedWsMessage),
            on_connected=recorder.on_connected,
        )

    connected, first, status, second = recorder.events
    assert connected == "connected"
    assert isinstance(first, EntityStateChangedWsMessage)
    assert isinstance(status, AppStatusChangedWsMessage)
    assert isinstance(second, EntityStateChangedWsMessage)
    assert (first.data.revision, second.data.revision, second.data.entity.value) == (5, 6, 2.5)
    assert ws_server.handshake_headers[0]["Authorization"] == f"Bearer {TEST_TOKEN}"


async def test_a_requested_type_that_fails_to_parse_ends_the_stream(
    ws_client: HassetteClient, ws_server: FakeWsServer
) -> None:
    broken = entity_message(5)
    del broken["data"]["boot_id"]
    ws_server.frames = [CONNECTED, broken]

    with pytest.raises(ResponseValidationError, match="boot_id"):
        await ws_client.listen(Recorder().on_message, types=(EntityStateChangedWsMessage,))


async def test_a_frame_that_is_not_a_json_object_ends_the_stream(
    ws_client: HassetteClient, ws_server: FakeWsServer
) -> None:
    ws_server.frames = [CONNECTED, [1, 2]]

    with pytest.raises(ResponseValidationError, match="not a JSON object"):
        await ws_client.listen(Recorder().on_message, types=(EntityStateChangedWsMessage,))


@pytest.mark.parametrize(
    "frames", [[], [STATUS_MESSAGE], [b"binary"]], ids=["closed-first", "wrong-first-message", "binary-first"]
)
async def test_a_stream_that_does_not_open_with_connected_raises(
    ws_client: HassetteClient, ws_server: FakeWsServer, frames: list[Any]
) -> None:
    ws_server.frames = frames
    recorder = Recorder()

    with pytest.raises(HassetteConnectionError):
        await ws_client.listen(
            recorder.on_message, types=(AppStatusChangedWsMessage,), on_connected=recorder.on_connected
        )
    assert recorder.events == []


async def test_connected_that_never_arrives_times_out(ws_client: HassetteClient, ws_server: FakeWsServer) -> None:
    ws_server.hold = True
    with pytest.raises(HassetteTimeoutError):
        await ws_client.listen(Recorder().on_message, types=(AppStatusChangedWsMessage,))


@pytest.mark.parametrize(
    ("status", "headers", "error"),
    [
        (401, {}, AuthenticationError),
        (403, {}, ForbiddenError),
        (302, {"Location": "/elsewhere"}, RedirectError),
        (200, {}, HassetteConnectionError),
    ],
    ids=["unauthorized", "forbidden", "redirect", "not-upgraded"],
)
async def test_a_rejected_handshake_maps_like_an_http_failure(
    ws_client: HassetteClient, ws_server: FakeWsServer, status: int, headers: dict[str, str], error: type[Exception]
) -> None:
    ws_server.status, ws_server.headers = status, headers

    with pytest.raises(error):
        await ws_client.listen(Recorder().on_message, types=(AppStatusChangedWsMessage,))


async def test_a_redirected_handshake_reports_its_first_hop(ws_client: HassetteClient, ws_server: FakeWsServer) -> None:
    ws_server.status, ws_server.headers = 302, {"Location": "/elsewhere"}

    with pytest.raises(RedirectError) as exc_info:
        await ws_client.listen(Recorder().on_message, types=(AppStatusChangedWsMessage,))
    assert (exc_info.value.status, exc_info.value.location) == (302, "/elsewhere")


async def test_an_unreachable_server_raises_a_connection_error(session: aiohttp.ClientSession) -> None:
    client = HassetteClient(session, "http://127.0.0.1:1", request_timeout=2)
    with pytest.raises(HassetteConnectionError):
        await client.listen(Recorder().on_message, types=(AppStatusChangedWsMessage,))


@pytest.mark.parametrize(
    "reset_class",
    [
        pytest.param(ConnectionResetError, id="aiohttp-3.10"),
        pytest.param(
            getattr(aiohttp, "ClientConnectionResetError", None),
            id="aiohttp-3.11+",
            marks=pytest.mark.skipif(
                not hasattr(aiohttp, "ClientConnectionResetError"), reason="added in aiohttp 3.11"
            ),
        ),
    ],
)
async def test_a_reset_raised_while_reading_maps_to_a_connection_error(
    ws_client: HassetteClient, ws_server: FakeWsServer, monkeypatch: pytest.MonkeyPatch, reset_class: type[Exception]
) -> None:
    """The automatic pong aiohttp sends runs outside ``receive()``'s own error handling, so a reset there raises."""
    ws_server.frames, ws_server.hold = [CONNECTED], True
    real_receive = aiohttp.ClientWebSocketResponse.receive
    calls = 0

    async def receive_then_reset(self: aiohttp.ClientWebSocketResponse, *args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            return await real_receive(self, *args, **kwargs)
        raise reset_class("Cannot write to closing transport")

    monkeypatch.setattr(aiohttp.ClientWebSocketResponse, "receive", receive_then_reset)

    with pytest.raises(HassetteConnectionError, match=reset_class.__name__):
        await ws_client.listen(Recorder().on_message, types=(AppStatusChangedWsMessage,))


async def test_an_exception_from_on_message_propagates(ws_client: HassetteClient, ws_server: FakeWsServer) -> None:
    ws_server.frames = [CONNECTED, STATUS_MESSAGE]

    async def explode(_: AppStatusChangedWsMessage) -> None:
        raise LookupError("caller bug")

    with pytest.raises(LookupError, match="caller bug"):
        await ws_client.listen(explode, types=(AppStatusChangedWsMessage,))


async def test_cancelling_closes_the_socket(ws_client: HassetteClient, ws_server: FakeWsServer) -> None:
    ws_server.frames, ws_server.hold = [CONNECTED], True
    connected = asyncio.Event()

    async def on_connected() -> None:
        connected.set()

    task = asyncio.create_task(
        ws_client.listen(Recorder().on_message, types=(AppStatusChangedWsMessage,), on_connected=on_connected)
    )
    await asyncio.wait_for(connected.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(ws_server.client_closed.wait(), 2)


async def test_a_server_that_stops_answering_pings_ends_the_stream(
    ws_client: HassetteClient, ws_server: FakeWsServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stream_module, "HEARTBEAT_SECONDS", 0.1)
    ws_server.frames, ws_server.hold, ws_server.autoping = [CONNECTED], True, False

    with pytest.raises(HassetteConnectionError, match="ended"):
        await asyncio.wait_for(ws_client.listen(Recorder().on_message, types=(AppStatusChangedWsMessage,)), 5)


@pytest.mark.parametrize(
    ("bad_type", "message"),
    [(ConnectedWsMessage, "pass on_connected instead"), (ConnectedData, "ConnectedData is not a /ws message")],
    ids=["connected", "payload-model"],
)
async def test_requesting_a_class_that_is_not_a_streamed_message_raises(
    ws_client: HassetteClient, bad_type: Any, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        await ws_client.listen(Recorder().on_message, types=(bad_type,))
