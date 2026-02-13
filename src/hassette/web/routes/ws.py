"""WebSocket endpoint for real-time updates."""

import asyncio
import json
import logging

import anyio
from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)

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
        logger.debug("WebSocket read error", exc_info=True)
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
            # Ensure all messages are JSON serializable (enums, dataclasses, etc.)
            message = json.loads(json.dumps(message, default=str))
            await websocket.send_json(message)
    except Exception as exc:
        if _is_disconnect(exc):
            return
        logger.debug("WebSocket send error", exc_info=True)
        raise


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    data_sync = websocket.app.state.hassette._data_sync_service
    queue = await data_sync.register_ws_client()
    ws_state: dict = {"subscribe_logs": False, "min_log_level": "INFO"}
    try:
        # Send initial connection info
        status = data_sync.get_system_status()
        await websocket.send_json(
            {
                "type": "connected",
                "data": {
                    "entity_count": status.entity_count,
                    "app_count": status.app_count,
                },
            }
        )
        async with anyio.create_task_group() as tg:
            tg.start_soon(_read_client, websocket, ws_state)
            tg.start_soon(_send_from_queue, websocket, queue, ws_state)
    except BaseException as exc:
        if isinstance(exc, BaseExceptionGroup):
            _, rest = exc.split(lambda e: _is_disconnect(e))
            if rest is not None:
                logger.debug("WebSocket connection error", exc_info=rest)
        elif not _is_disconnect(exc):
            logger.debug("WebSocket connection error", exc_info=True)
    finally:
        await data_sync.unregister_ws_client(queue)
