"""A scriptable Home Assistant WebSocket server for reconnect-loop tests.

Speaks the subset of HA's WebSocket API that ``WebsocketService`` uses to connect: the
``auth_required`` / ``auth`` / ``auth_ok`` handshake, ``subscribe_events``, ``get_config`` and
``get_states``. Each knob below scripts one failure mode the reconnect loop has to classify
(design/specs/131-ha-restart-reconnect), and the counters let a test assert how many attempts
the loop made. Runs on the test's own event loop via ``aiohttp.test_utils.TestServer``.

``stop()`` closes the listening socket so the next connection is refused, the same as a
stopped HA container; ``start()`` brings it back on the same port.
"""

from typing import Any

from aiohttp import WSCloseCode, web
from aiohttp.test_utils import TestServer

from tests.support.uvicorn import get_free_port

WS_PATH = "/api/websocket"


class FakeHomeAssistant:
    """A Home Assistant WebSocket endpoint whose answers a test scripts."""

    def __init__(self) -> None:
        self.port = get_free_port()
        self.server: TestServer | None = None

        self.handshake_status: int | None = None
        """When set, answer the upgrade request with this HTTP status instead of a WebSocket."""
        self.auth_valid = True
        self.core_states: list[str] = ["RUNNING"]
        """States returned by successive ``get_config`` calls on one connection; the last repeats."""
        self.get_states_payload: list[dict[str, Any]] = []
        self.unanswered_commands: set[str] = set()
        """Command types the server receives but never replies to."""

        self.connections = 0
        """WebSocket upgrades accepted."""
        self.auth_attempts = 0
        self.get_config_calls = 0
        self.sockets: list[web.WebSocketResponse] = []

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}{WS_PATH}"

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get(WS_PATH, self.handle)
        self.server = TestServer(app, host="127.0.0.1", port=self.port)
        await self.server.start_server()

    async def stop(self) -> None:
        """Close every connection with 1001 (as an HA restart does) and stop listening."""
        await self.drop_all(WSCloseCode.GOING_AWAY)
        if self.server is not None:
            await self.server.close()
            self.server = None

    async def drop_all(self, code: int = WSCloseCode.GOING_AWAY) -> None:
        for ws in list(self.sockets):
            await ws.close(code=code)

    async def send_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Send an event to every open, authenticated connection."""
        for ws in list(self.sockets):
            await ws.send_json(
                {
                    "id": 1,
                    "type": "event",
                    "event": {
                        "event_type": event_type,
                        "data": data or {},
                        "origin": "LOCAL",
                        "time_fired": "2026-10-12T10:00:00.000000+00:00",
                        "context": {"id": "fake-context", "parent_id": None, "user_id": None},
                    },
                }
            )

    async def handle(self, request: web.Request) -> web.StreamResponse:
        if self.handshake_status is not None:
            return web.Response(status=self.handshake_status)

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        await ws.send_json({"type": "auth_required", "ha_version": "2026.10.0"})
        msg = await ws.receive_json()
        self.auth_attempts += 1
        if msg.get("type") != "auth" or not self.auth_valid:
            await ws.send_json({"type": "auth_invalid", "message": "Invalid access token or password"})
            await ws.close()
            return ws
        await ws.send_json({"type": "auth_ok", "ha_version": "2026.10.0"})

        self.sockets.append(ws)
        core_states = iter(self.core_states)
        core_state = self.core_states[0]
        try:
            async for raw in ws:
                if raw.type is not web.WSMsgType.TEXT:
                    continue
                msg = raw.json()
                if msg.get("type") in self.unanswered_commands:
                    continue
                match msg.get("type"):
                    case "get_config":
                        self.get_config_calls += 1
                        core_state = next(core_states, core_state)
                        await self.reply(ws, msg, {"state": core_state, "version": "2026.10.0"})
                    case "get_states":
                        await self.reply(ws, msg, self.get_states_payload)
                    case _:
                        await self.reply(ws, msg, None)
        finally:
            self.sockets.remove(ws)
        return ws

    @staticmethod
    async def reply(ws: web.WebSocketResponse, msg: dict[str, Any], result: Any) -> None:
        await ws.send_json({"id": msg["id"], "type": "result", "success": True, "result": result})
