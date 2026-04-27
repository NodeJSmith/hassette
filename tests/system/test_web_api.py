"""System tests for the monitoring web API — HTTP endpoints and WebSocket."""

import asyncio
import json
from typing import Any

import httpx
import pytest
from websockets.asyncio.client import connect as ws_connect

from .conftest import make_web_system_config, startup_context, toggle_and_capture, wait_for_web_server

pytestmark = [pytest.mark.system]

_ENTITY = "light.kitchen_lights"
_DOMAIN = "light"


async def test_health_endpoint(ha_container: str, tmp_path):
    """GET /api/health returns 200 and a JSON body with a websocket_connected field."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config) as _hassette:
        await wait_for_web_server(base_url)

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base_url}/api/health", timeout=10.0)

        assert r.status_code == 200
        body: dict[str, Any] = r.json()
        assert "websocket_connected" in body


async def test_apps_endpoint(ha_container: str, tmp_path):
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


async def test_config_endpoint(ha_container: str, tmp_path):
    """GET /api/config returns 200 and a ConfigResponse-shaped JSON body."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config) as _hassette:
        await wait_for_web_server(base_url)

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base_url}/api/config", timeout=10.0)

        assert r.status_code == 200
        body: dict[str, Any] = r.json()
        assert "run_web_api" in body
        assert "web_api_port" in body
        assert "log_level" in body
        assert body["run_web_api"] is True


async def test_telemetry_after_activity(ha_container: str, tmp_path):
    """After a bus handler fires, GET /api/dashboard/kpis shows non-zero invocation count."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        await wait_for_web_server(base_url)

        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        await toggle_and_capture(bus, hassette.api, _ENTITY)

        kpis: dict[str, Any] = {}
        deadline = asyncio.get_running_loop().time() + 20.0
        async with httpx.AsyncClient() as client:
            while asyncio.get_running_loop().time() < deadline:
                r = await client.get(f"{base_url}/api/telemetry/dashboard/kpis", timeout=5.0)
                if r.status_code == 200:
                    kpis = r.json()
                    if kpis.get("total_invocations", 0) > 0:
                        break
                await asyncio.sleep(0.3)

        assert kpis.get("total_invocations", 0) > 0, f"Dashboard KPIs still show 0 invocations after polling: {kpis}"


async def test_websocket_receives_events(ha_container: str, tmp_path):
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

            await hassette.api.call_service(_DOMAIN, "toggle", {"entity_id": _ENTITY})

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
