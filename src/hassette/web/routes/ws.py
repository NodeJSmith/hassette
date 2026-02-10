"""WebSocket endpoint for real-time updates."""

import asyncio
import logging

import anyio
from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


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
                ws_state["min_log_level"] = sub_data.get("min_log_level", "INFO")
    except (WebSocketDisconnect, anyio.ClosedResourceError):
        raise
    except Exception:
        logger.debug("WebSocket read error", exc_info=True)
        raise


async def _send_from_queue(websocket: WebSocket, queue: asyncio.Queue, ws_state: dict) -> None:
    """Send messages from the broadcast queue to the client."""
    log_levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    try:
        while True:
            message = await queue.get()
            # Filter log messages based on subscription
            if message.get("type") == "log":
                if not ws_state.get("subscribe_logs", False):
                    continue
                msg_level = log_levels.get(message.get("data", {}).get("level", ""), 0)
                min_level = log_levels.get(ws_state.get("min_log_level", "INFO"), 20)
                if msg_level < min_level:
                    continue
            await websocket.send_json(message)
    except (WebSocketDisconnect, anyio.ClosedResourceError):
        raise
    except Exception:
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
    except (WebSocketDisconnect, anyio.ClosedResourceError):
        pass
    except Exception:
        logger.debug("WebSocket connection error", exc_info=True)
    finally:
        data_sync.unregister_ws_client(queue)
