"""WebSocket endpoint for real-time updates."""

import asyncio
import time
from logging import getLogger

import anyio
from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from hassette.web.auth import WS_POLICY_VIOLATION_CLOSE_CODE, authorize_ws
from hassette.web.mappers import connected_payload_from

router = APIRouter(tags=["websocket"])
LOGGER = getLogger(__name__)

# Exception types that indicate a normal client disconnect.
_DISCONNECT_ERRORS = (
    WebSocketDisconnect,
    anyio.ClosedResourceError,
    ConnectionResetError,
    BrokenPipeError,
)


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


async def _read_client(websocket: WebSocket, ws_state: dict) -> None:
    """Read messages from the client and handle ping/pong and subscriptions."""
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "subscribe":
                sub_data = data.get("data", {})
                # A client may still send `min_log_level` (harmless, silently ignored) —
                # log_hint carries no level, so filtering happens client-side after the REST
                # catch-up fetch instead.
                ws_state["subscribe_logs"] = sub_data.get("logs", False)
    except Exception as exc:
        if _is_disconnect(exc):
            return
        LOGGER.debug("WebSocket read error", exc_info=True)
        raise


async def _send_from_queue(websocket: WebSocket, queue: asyncio.Queue, ws_state: dict) -> None:
    """Send messages from the broadcast queue to the client."""
    try:
        while True:
            message = await queue.get()
            if message is None:
                break  # shutdown sentinel
            # Filter log_hint messages based on subscription. log_hint carries no level, so
            # min_log_level filtering has moved client-side, after the REST catch-up fetch.
            msg_type = message.get("type")
            if msg_type == "log_hint" and not ws_state.get("subscribe_logs", False):
                continue
            await websocket.send_json(message)
    except Exception as exc:
        if _is_disconnect(exc):
            return
        LOGGER.debug("WebSocket send error", exc_info=True)
        raise


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    if not authorize_ws(websocket):
        await websocket.close(code=WS_POLICY_VIOLATION_CLOSE_CODE)
        return
    await websocket.accept()
    runtime = websocket.app.state.hassette.runtime_query_service
    queue = await runtime.register_ws_client()
    ws_state: dict = {"subscribe_logs": False}
    try:
        # Send initial connection info (includes uptime_seconds for time-window filtering)
        status = runtime.get_system_status()
        payload = connected_payload_from(status)
        await websocket.send_json({"type": "connected", "data": payload.model_dump(), "timestamp": time.time()})
        async with anyio.create_task_group() as tg:
            tg.start_soon(_read_client, websocket, ws_state)
            tg.start_soon(_send_from_queue, websocket, queue, ws_state)
    except BaseException as exc:  # noqa: ASYNC103 — disconnect errors are intentionally suppressed below
        if isinstance(exc, asyncio.CancelledError):
            raise
        if isinstance(exc, BaseExceptionGroup):
            _, rest = exc.split(_is_disconnect)
            if rest is not None:
                LOGGER.debug("WebSocket connection error", exc_info=rest)
        elif not _is_disconnect(exc):
            LOGGER.debug("WebSocket connection error", exc_info=True)
    finally:
        await runtime.unregister_ws_client(queue)
