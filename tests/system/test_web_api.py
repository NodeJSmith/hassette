"""System tests for the monitoring web API — HTTP endpoints and WebSocket."""

import asyncio
import json
import time
from typing import Any

import httpx
import pytest
from websockets import connect as ws_connect

from hassette.test_utils import wait_for
from hassette.web.config_view import MASK_SENTINEL

from .conftest import HA_TOKEN, make_web_system_config, startup_context, toggle_and_capture, wait_for_web_server

pytestmark = [pytest.mark.system]

ENTITY = "light.kitchen_lights"
DOMAIN = "light"


async def test_health_endpoint(ha_container: str, tmp_path) -> None:
    """GET /api/health returns 200 and a JSON body with a websocket_connected field."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config) as _hassette:
        await wait_for_web_server(base_url)

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base_url}/api/health", timeout=10.0)

        assert r.status_code == 200
        body: dict[str, Any] = r.json()
        assert "websocket_connected" in body


async def test_apps_endpoint(ha_container: str, tmp_path) -> None:
    """GET /api/apps returns 200 and an AppStatusResponse-shaped JSON body."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config) as _hassette:
        await wait_for_web_server(base_url)

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base_url}/api/apps", timeout=10.0)

        assert r.status_code == 200
        body: dict[str, Any] = r.json()
        assert "total" in body
        assert "running" in body
        assert "failed" in body
        assert "apps" in body
        assert isinstance(body["apps"], list)


async def test_config_endpoint(ha_container: str, tmp_path) -> None:
    """GET /api/config returns 200 with the ConfigSchemaResponse envelope."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config) as _hassette:
        await wait_for_web_server(base_url)

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base_url}/api/config", timeout=10.0)

        assert r.status_code == 200
        body: dict[str, Any] = r.json()
        assert "config_schema" in body
        assert "config_values" in body
        config_values = body["config_values"]
        assert "web_api" in config_values
        assert "logging" in config_values
        assert config_values["web_api"]["run"] is True
        assert config_values["web_api"]["port"] > 0


async def test_config_endpoint_masks_token(ha_container: str, tmp_path) -> None:
    """GET /api/config never leaks the plaintext HA token on a live response.

    The plaintext SecretStr must never appear in the body, and the token field must
    render as the mask sentinel. Unit and integration tests mock this serialization
    boundary, so a regression (e.g. model_dump() instead of model_dump(mode="json"))
    would pass them and still leak the token from a real running instance.
    """
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config) as _hassette:
        await wait_for_web_server(base_url)

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base_url}/api/config", timeout=10.0)

        assert r.status_code == 200
        config_values: dict[str, Any] = r.json()["config_values"]
        assert HA_TOKEN not in r.text
        assert config_values["token"] == MASK_SENTINEL


async def test_telemetry_after_activity(ha_container: str, tmp_path) -> None:
    """After a bus handler fires, telemetry shows non-zero invocation count."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        await wait_for_web_server(base_url)

        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        app_key = hassette.app_key
        pre_toggle_ts = time.time()
        await toggle_and_capture(bus, hassette.api, ENTITY)

        async with httpx.AsyncClient() as client:

            async def _has_invocations() -> bool:
                r = await client.get(
                    f"{base_url}/api/telemetry/app/{app_key}/health",
                    params={"source_tier": "framework"},
                    timeout=5.0,
                )
                if r.status_code != 200:
                    return False
                data = r.json()
                ts = data.get("last_activity_ts")
                return ts is not None and ts >= pre_toggle_ts

            await wait_for(_has_invocations, timeout=20.0, interval=0.3, desc="telemetry to show handler activity")


async def test_websocket_receives_events(ha_container: str, tmp_path) -> None:
    """Connecting to /api/ws yields an initial 'connected' message then event messages on activity."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    ws_url = base_url.replace("http://", "ws://", 1) + "/api/ws"

    async with startup_context(config) as hassette:
        await wait_for_web_server(base_url)

        async with ws_connect(ws_url, ping_interval=None) as ws:
            raw_connected = await asyncio.wait_for(ws.recv(), timeout=10.0)
            connected_msg: dict[str, Any] = json.loads(raw_connected)
            assert connected_msg["type"] == "connected"
            assert "data" in connected_msg
            assert "timestamp" in connected_msg

            await hassette.api.call_service(DOMAIN, "toggle", {"entity_id": ENTITY})

            event_msg: dict[str, Any] | None = None
            deadline = asyncio.get_running_loop().time() + 15.0
            while asyncio.get_running_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    msg: dict[str, Any] = json.loads(raw)
                    if msg.get("type") != "connected":
                        event_msg = msg
                        break
                except TimeoutError:
                    continue

            assert event_msg is not None, "No event message received over WebSocket after toggling light"
            assert "type" in event_msg
