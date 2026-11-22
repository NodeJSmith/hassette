"""WebSocket endpoint for real-time updates."""

import asyncio
import time
from dataclasses import dataclass
from logging import getLogger

import anyio
from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from hassette.web.auth import authorize_ws
from hassette.web.auth.trusted_proxies import peer_address_or_unknown
from hassette.web.mappers import connected_data_from
from hassette.web.middleware import failed_auth_tracker, unauthorized_response

router = APIRouter(tags=["websocket"])
LOGGER = getLogger(__name__)

# Exception types that indicate a normal client disconnect.
_DISCONNECT_ERRORS = (
    WebSocketDisconnect,
    anyio.ClosedResourceError,
    ConnectionResetError,
    BrokenPipeError,
)


@dataclass
class WsConnectionState:
    """Per-connection state shared by the reader and sender tasks."""

    subscribe_logs: bool = False


def _is_disconnect(exc: BaseException) -> bool:
    """Check if an exception represents a normal WebSocket disconnect.

    Covers typed disconnect exceptions plus the RuntimeError that Starlette/ASGI
    raises when sending on a socket whose close frame has already been processed.
    """
    if isinstance(exc, _DISCONNECT_ERRORS):
        return True
    if isinstance(exc, RuntimeError):
        msg = str(exc)
        return "websocket.send" in msg or "websocket.close" in msg
    return False


async def _read_client(websocket: WebSocket, state: WsConnectionState, scope: anyio.CancelScope) -> None:
    """Read messages from the client and handle ping/pong and subscriptions.

    Cancels ``scope`` when reading stops for any reason, so a client disconnect ends the whole
    connection instead of leaving the sender blocked on its queue.
    """
    try:
        while True:
            data = await websocket.receive_json()
            if not isinstance(data, dict):
                continue
            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "subscribe":
                sub_data = data.get("data", {})
                if not isinstance(sub_data, dict):
                    sub_data = {}
                state.subscribe_logs = bool(sub_data.get("logs", False))
    except Exception as exc:
        if _is_disconnect(exc):
            return
        LOGGER.debug("WebSocket read error", exc_info=True)
        raise
    finally:
        scope.cancel()


async def _send_from_queue(websocket: WebSocket, queue: asyncio.Queue, state: WsConnectionState) -> None:
    """Send messages from the broadcast queue to the client."""
    try:
        while True:
            message = await queue.get()
            if message is None:
                break  # shutdown sentinel
            # log_hint carries no level; clients filter by level after the /logs/recent refetch it triggers.
            msg_type = message.get("type")
            if msg_type == "log_hint" and not state.subscribe_logs:
                continue
            await websocket.send_json(message)
    except Exception as exc:
        if _is_disconnect(exc):
            return
        LOGGER.debug("WebSocket send error", exc_info=True)
        raise


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Stream runtime events to an authorized client until it disconnects.

    An unauthorized handshake gets the same 401 problem response REST sends and counts as a failed auth
    attempt. Sending it needs the ASGI WebSocket Denial Response extension, which the uvicorn hassette runs
    provides; without it Starlette raises ``RuntimeError``. Accepted clients receive a ``connected`` message
    first, then queued events; clients can subscribe to log records.
    """
    if not authorize_ws(websocket):
        failed_auth_tracker(websocket).record(peer_address_or_unknown(websocket))
        await websocket.send_denial_response(unauthorized_response())
        return
    await websocket.accept()
    runtime = websocket.app.state.hassette.runtime_query_service
    queue = await runtime.register_ws_client()
    state = WsConnectionState()
    try:
        # Send initial connection info (includes uptime_seconds for time-window filtering)
        status = runtime.get_system_status()
        connected = connected_data_from(status)
        await websocket.send_json({"type": "connected", "data": connected.model_dump(), "timestamp": time.time()})
        async with anyio.create_task_group() as tg:
            tg.start_soon(_read_client, websocket, state, tg.cancel_scope)
            tg.start_soon(_send_from_queue, websocket, queue, state)
    except BaseException as exc:  # noqa: ASYNC103 — disconnect errors are intentionally suppressed below
        if isinstance(exc, asyncio.CancelledError):
            raise
        if isinstance(exc, BaseExceptionGroup):
            _, rest = exc.split(_is_disconnect)
            if rest is not None:
                LOGGER.warning("WebSocket connection error", exc_info=rest)
        elif not _is_disconnect(exc):
            LOGGER.warning("WebSocket connection error", exc_info=True)
    finally:
        await runtime.unregister_ws_client(queue)
