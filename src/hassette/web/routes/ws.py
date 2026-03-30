"""WebSocket endpoint for real-time updates."""

import asyncio
import time
from logging import getLogger

import anyio
from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from hassette.web.models import ConnectedPayload
from hassette.web.telemetry_helpers import safe_session_id

router = APIRouter(tags=["websocket"])
LOGGER = getLogger(__name__)

_LOG_LEVELS: dict[str, int] = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

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
                ws_state["subscribe_logs"] = sub_data.get("logs", False)
                raw_level = sub_data.get("min_log_level", "INFO")
                level = raw_level.upper() if isinstance(raw_level, str) else "INFO"
                ws_state["min_log_level"] = level if level in _LOG_LEVELS else "INFO"
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
            # Filter log messages based on subscription
            if message.get("type") == "log":
                if not ws_state.get("subscribe_logs", False):
                    continue
                msg_level = _LOG_LEVELS.get(message.get("data", {}).get("level", ""), 0)
                min_level = _LOG_LEVELS.get(ws_state.get("min_log_level", "INFO"), 20)
                if msg_level < min_level:
                    continue
            await websocket.send_json(message)
    except Exception as exc:
        if _is_disconnect(exc):
            return
        LOGGER.debug("WebSocket send error", exc_info=True)
        raise


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    runtime = websocket.app.state.hassette.runtime_query_service
    queue = await runtime.register_ws_client()
    ws_state: dict = {"subscribe_logs": False, "min_log_level": "INFO"}
    try:
        # Send initial connection info (includes session_id for telemetry scoping)
        status = runtime.get_system_status()
        payload = ConnectedPayload(
            session_id=safe_session_id(runtime),
            entity_count=status.entity_count,
            app_count=status.app_count,
        )
        await websocket.send_json({"type": "connected", "data": payload.model_dump(), "timestamp": time.time()})
        async with anyio.create_task_group() as tg:
            tg.start_soon(_read_client, websocket, ws_state)
            tg.start_soon(_send_from_queue, websocket, queue, ws_state)
    except BaseException as exc:
        if isinstance(exc, BaseExceptionGroup):
            _, rest = exc.split(_is_disconnect)
            if rest is not None:
                LOGGER.debug("WebSocket connection error", exc_info=rest)
        elif not _is_disconnect(exc):
            LOGGER.debug("WebSocket connection error", exc_info=True)
    finally:
        await runtime.unregister_ws_client(queue)
