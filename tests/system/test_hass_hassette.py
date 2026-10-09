"""End-to-end test of the hass-hassette companion integration against a live hassette.

The HA container installs the release pinned by ``HASS_HASSETTE_VERSION`` (scripts/docker/.env);
this test configures it against hassette running in the pytest process and drives an app from HA.
A Renovate bump of that pin runs this test, which is how a release that changed the integration's
entity scheme (``APP_ENTITY_KEYS``) or config flow fields shows up.
"""

import json
import secrets
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from websockets import connect as ws_connect

from hassette.testing import wait_for

from .conftest import HA_TOKEN, make_web_system_config, startup_context, wait_for_web_server

pytestmark = [pytest.mark.system]

INTEGRATION = "hassette"
# The integration's per-app entities: unique_id "{app_key}-{key}", one of each per app device.
APP_ENTITY_KEYS = ("running", "reload", "status")
# The extra_hosts alias tests/system/docker-compose.yml gives the HA container for this host.
HOST_FROM_HA = "host.docker.internal"
# The fixture app (tests/system/apps/trivial_app.py) whose switch the test turns off.
TOGGLED_APP = "TrivialApp"

# Starting the config flow makes HA pip-install the integration's requirements in the container.
# Kept under the per-test --timeout (120 s) that noxfile.py's _run_system_tests sets.
FLOW_START_TIMEOUT_SECONDS = 90.0
FLOW_SUBMIT_TIMEOUT_SECONDS = 30.0
# Covers one 30 s coordinator poll with margin: entities register, and the switch reflects state.
POLL_TIMEOUT_SECONDS = 60.0
# A stop answers once the app's shutdown finishes; hassette's own shutdown budget is well under this.
ACTION_TIMEOUT_SECONDS = 60.0
HA_POLL_INTERVAL_SECONDS = 1.0
APP_POLL_INTERVAL_SECONDS = 0.5
# Entropy of the per-run web API token the test hands HA.
TOKEN_BYTES = 32


async def ha_ws(ha_url: str, command: dict[str, Any]) -> Any:
    """Send one WebSocket command to HA on its own connection and return its ``result``."""
    async with ws_connect(f"ws{ha_url.removeprefix('http')}/api/websocket") as ws:
        json.loads(await ws.recv())  # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        auth = json.loads(await ws.recv())
        assert auth["type"] == "auth_ok", auth
        await ws.send(json.dumps({"id": 1, **command}))
        reply = json.loads(await ws.recv())
    assert reply["success"], reply
    return reply["result"]


async def create_entry(ha: httpx.AsyncClient, hassette_url: str, token: str) -> str:
    """Run the integration's config flow against ``hassette_url`` and return the new entry id."""
    r = await ha.post(
        "/api/config/config_entries/flow",
        json={"handler": INTEGRATION, "show_advanced_options": False},
        timeout=FLOW_START_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    form = r.json()
    assert form["type"] == "form", form
    assert form["step_id"] == "user", form

    r = await ha.post(
        f"/api/config/config_entries/flow/{form['flow_id']}",
        json={"url": hassette_url, "api_token": token, "verify_ssl": True},
        timeout=FLOW_SUBMIT_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    result = r.json()
    assert result["type"] == "create_entry", result
    return result["result"]["entry_id"]


async def app_entities(ha_url: str, entry_id: str) -> dict[str, dict[str, Any]]:
    """The entry's entity registry entries, keyed by unique_id."""
    entries = await ha_ws(ha_url, {"type": "config/entity_registry/list"})
    return {e["unique_id"]: e for e in entries if e["config_entry_id"] == entry_id}


async def app_key_by_device(ha_url: str) -> dict[str, str]:
    """Map each of the integration's app device ids to the app_key in its device identifier."""
    devices = await ha_ws(ha_url, {"type": "config/device_registry/list"})
    return {
        device["id"]: app_key
        for device in devices
        for domain, app_key in device["identifiers"]
        if domain == INTEGRATION
    }


async def wait_for_app_entities(ha_url: str, entry_id: str, expected: set[str]) -> dict[str, dict[str, Any]]:
    """Wait until every ``expected`` unique_id is registered for the entry; return the entry's entities."""
    entities: dict[str, dict[str, Any]] = {}

    async def all_registered() -> bool:
        nonlocal entities
        entities = await app_entities(ha_url, entry_id)
        return expected <= entities.keys()

    await wait_for(all_registered, timeout=POLL_TIMEOUT_SECONDS, interval=HA_POLL_INTERVAL_SECONDS, desc="app entities")
    return entities


def switch_is(ha: httpx.AsyncClient, switch: str, expected_state: str):
    """A ``wait_for`` condition: HA reports ``switch`` in ``expected_state``."""

    async def check() -> bool:
        resp = await ha.get(f"/api/states/{switch}")
        resp.raise_for_status()
        return resp.json()["state"] == expected_state

    return check


def app_is_stopped(api: httpx.AsyncClient, app_key: str):
    """A ``wait_for`` condition: hassette reports ``app_key`` as stopped."""

    async def check() -> bool:
        resp = await api.get(f"/api/apps/{app_key}")
        resp.raise_for_status()
        return resp.json()["status"] == "stopped"

    return check


async def test_integration_controls_hassette_apps(ha_container: str, tmp_path: Path, system_app_dir: Path) -> None:
    """Each app becomes a device with its entities, and turning its switch off stops it in hassette."""
    # HA reaches hassette from its container through the docker bridge, so the web API binds every
    # interface; a per-run token keeps that from exposing a known credential on the LAN.
    token = secrets.token_urlsafe(TOKEN_BYTES)
    config, base_url = make_web_system_config(ha_container, tmp_path, host="0.0.0.0", auth_token=token)
    # make_web_system_config starts with an empty app dir; this test needs the fixture apps loaded.
    config.apps.autodetect = True
    config.apps.directory = system_app_dir

    async with (
        startup_context(config) as hassette,
        httpx.AsyncClient(base_url=ha_container, headers={"Authorization": f"Bearer {HA_TOKEN}"}) as ha,
        httpx.AsyncClient(base_url=base_url, headers={"Authorization": f"Bearer {token}"}) as api,
    ):
        await wait_for_web_server(base_url)
        app_keys = set(hassette.app_handler.registry.app_keys())
        [toggled_key] = [key for key in app_keys if TOGGLED_APP in key]

        entry_id = await create_entry(ha, f"http://{HOST_FROM_HA}:{config.web_api.port}", token)
        try:
            expected = {f"{key}-{suffix}" for key in app_keys for suffix in APP_ENTITY_KEYS}
            entities = await wait_for_app_entities(ha_container, entry_id, expected)

            device_app = await app_key_by_device(ha_container)
            for unique_id in expected:
                assert device_app[entities[unique_id]["device_id"]] == unique_id.rsplit("-", 1)[0]

            switch = entities[f"{toggled_key}-running"]["entity_id"]
            poll = {"timeout": POLL_TIMEOUT_SECONDS, "interval": HA_POLL_INTERVAL_SECONDS}
            await wait_for(switch_is(ha, switch, "on"), desc=f"{switch} on", **poll)

            resp = await ha.post(
                "/api/services/switch/turn_off", json={"entity_id": switch}, timeout=ACTION_TIMEOUT_SECONDS
            )
            resp.raise_for_status()

            await wait_for(
                app_is_stopped(api, toggled_key),
                timeout=ACTION_TIMEOUT_SECONDS,
                interval=APP_POLL_INTERVAL_SECONDS,
                desc=f"{toggled_key} stopped",
            )
            await wait_for(switch_is(ha, switch, "off"), desc=f"{switch} off", **poll)
        finally:
            # Unload before hassette stops, so the session-scoped HA isn't left polling a dead server.
            # Best-effort: raising here would replace the assertion error that brought us here.
            await ha.delete(f"/api/config/config_entries/entry/{entry_id}")
