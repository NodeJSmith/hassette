"""End-to-end test of the hass-hassette companion integration against a live hassette.

The HA container installs the release pinned by ``HASS_HASSETTE_VERSION`` (scripts/docker/.env);
these tests configure it against hassette running in the pytest process, drive an app from HA, send a
message from HA to hassette, and run an app instance's declared button, switch and sensor through a
hassette restart, an HA restart and a dropped declaration. A Renovate bump of that pin runs them, which
is how a release that changed the integration's entity scheme (``APP_ENTITY_KEYS``), config flow
fields, or the ``hassette.send`` event contract (event type ``hassette_message``, data ``{name, data}``) shows up.
"""

import asyncio
import json
import secrets
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from websockets import connect as ws_connect

from hassette import D, Hassette
from hassette.config.config import HassetteConfig
from hassette.events import HassetteMessageEvent
from hassette.testing import wait_for

from .conftest import (
    HA_CONTAINER_NAME,
    HA_TOKEN,
    in_own_context,
    make_web_system_config,
    startup_context,
    wait_for_ha_ready,
    wait_for_web_server,
    with_app_entries,
)

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
# A stop answers once the app's shutdown finishes; an instance stop's entry deadline is well under this.
ACTION_TIMEOUT_SECONDS = 60.0
HA_POLL_INTERVAL_SECONDS = 1.0
APP_POLL_INTERVAL_SECONDS = 0.5
# Entropy of the per-run web API token the test hands HA.
TOKEN_BYTES = 32
# The message the hassette.send test sends, and how long it waits for the handler to see it.
MESSAGE_NAME = "system_test_message"
MESSAGE_TIMEOUT_SECONDS = 15.0
# The app fixture whose instance declares entities (tests/system/declaring_apps/declaring_app.py), and the keys
# it declares. Its own directory keeps the tests that load tests/system/apps/ from declaring anything.
DECLARING_APP_DIR = Path(__file__).parent / "declaring_apps"
DECLARED_KEYS = ("presses", "ping", "occupied")
# A value the app sets reaches HA over hass-hassette's /ws push in about a second. Well under one poll (30 s,
# hass-hassette's SCAN_INTERVAL), so the test fails when push breaks rather than passing on polling alone.
PUSH_TIMEOUT_SECONDS = 10.0
# The count the test sets from the app's side, outside any HA action, to check it arrives by push.
PUSHED_COUNT = 5
# The declared-entity tests start hassette more than once and may run the session's first config flow, whose
# requirement install alone can take FLOW_START_TIMEOUT_SECONDS; the 120 s default per-test timeout is too short.
DECLARED_TEST_TIMEOUT_SECONDS = 300


@dataclass
class SystemMessage:
    """The ``data`` model the hassette.send test's handler annotates with ``D.MessageData``."""

    room: str
    count: int


def ha_client(ha_url: str) -> httpx.AsyncClient:
    """An HTTP client for HA's REST API, authenticated with the system tests' HA token."""
    return httpx.AsyncClient(base_url=ha_url, headers={"Authorization": f"Bearer {HA_TOKEN}"})


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


async def remove_entry(ha: httpx.AsyncClient, entry_id: str) -> None:
    """Remove an integration entry, best-effort: raising here would replace the assertion error that led here."""
    with suppress(httpx.HTTPError):
        await ha.delete(f"/api/config/config_entries/entry/{entry_id}")


@asynccontextmanager
async def config_entry(ha: httpx.AsyncClient, hassette_url: str, token: str) -> AsyncIterator[str]:
    """Create an integration entry for ``hassette_url``, yield its id, and remove it on exit.

    Removal runs before hassette stops, so the session-scoped HA isn't left polling a dead server.
    """
    entry_id = await create_entry(ha, hassette_url, token)
    try:
        yield entry_id
    finally:
        await remove_entry(ha, entry_id)


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


def state_is(ha: httpx.AsyncClient, entity_id: str, expected_state: str):
    """A ``wait_for`` condition: HA reports ``entity_id`` in ``expected_state``."""

    async def check() -> bool:
        resp = await ha.get(f"/api/states/{entity_id}")
        # Not in the state machine yet, as right after HA restarts until the integration has loaded.
        if resp.status_code == HTTPStatus.NOT_FOUND:
            return False
        resp.raise_for_status()
        return resp.json()["state"] == expected_state

    return check


async def call_service(ha: httpx.AsyncClient, domain: str, service: str, entity_id: str) -> None:
    """Call an HA action on one entity and wait for HA to answer."""
    resp = await ha.post(
        f"/api/services/{domain}/{service}", json={"entity_id": entity_id}, timeout=ACTION_TIMEOUT_SECONDS
    )
    resp.raise_for_status()


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
    config = with_app_entries(config, system_app_dir)

    async with (
        startup_context(config) as hassette,
        ha_client(ha_container) as ha,
        httpx.AsyncClient(base_url=base_url, headers={"Authorization": f"Bearer {token}"}) as api,
    ):
        await wait_for_web_server(base_url)
        app_keys = set(hassette.app_handler.registry.app_keys())
        [toggled_key] = [key for key in app_keys if TOGGLED_APP in key]

        async with config_entry(ha, f"http://{HOST_FROM_HA}:{config.web_api.port}", token) as entry_id:
            expected = {f"{key}-{suffix}" for key in app_keys for suffix in APP_ENTITY_KEYS}
            entities = await wait_for_app_entities(ha_container, entry_id, expected)

            device_app = await app_key_by_device(ha_container)
            for unique_id in expected:
                assert device_app[entities[unique_id]["device_id"]] == unique_id.rsplit("-", 1)[0]

            switch = entities[f"{toggled_key}-running"]["entity_id"]
            poll = {"timeout": POLL_TIMEOUT_SECONDS, "interval": HA_POLL_INTERVAL_SECONDS}
            await wait_for(state_is(ha, switch, "on"), desc=f"{switch} on", **poll)

            await call_service(ha, "switch", "turn_off", switch)

            await wait_for(
                app_is_stopped(api, toggled_key),
                timeout=ACTION_TIMEOUT_SECONDS,
                interval=APP_POLL_INTERVAL_SECONDS,
                desc=f"{toggled_key} stopped",
            )
            await wait_for(state_is(ha, switch, "off"), desc=f"{switch} off", **poll)


async def test_send_action_delivers_a_typed_message(ha_container: str, tmp_path: Path) -> None:
    """``hassette.send`` in HA reaches an ``on_hassette_message`` handler as a typed event and typed data."""
    # hassette.send checks hassette's health through the entry before firing, so it needs one too.
    token = secrets.token_urlsafe(TOKEN_BYTES)
    config, base_url = make_web_system_config(ha_container, tmp_path, host="0.0.0.0", auth_token=token)
    received: list[tuple[HassetteMessageEvent, SystemMessage]] = []

    async def on_message(event: HassetteMessageEvent, data: D.MessageData[SystemMessage]) -> None:
        received.append((event, data))

    async with (
        startup_context(config) as hassette,
        ha_client(ha_container) as ha,
    ):
        await wait_for_web_server(base_url)
        await hassette.bus.on_hassette_message(MESSAGE_NAME, handler=on_message, name="system.message")

        async with config_entry(ha, f"http://{HOST_FROM_HA}:{config.web_api.port}", token):
            resp = await ha.post(
                "/api/services/hassette/send",
                json={"name": MESSAGE_NAME, "data": {"room": "kitchen", "count": "2"}},
                timeout=ACTION_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            await wait_for(lambda: bool(received), timeout=MESSAGE_TIMEOUT_SECONDS, desc=f"{MESSAGE_NAME} handled")

    [(event, data)] = received
    assert event.payload.data.name == MESSAGE_NAME
    assert event.payload.data.data == {"room": "kitchen", "count": "2"}
    assert data == SystemMessage(room="kitchen", count=2)


def with_declare_switch(config: HassetteConfig, declare_switch: bool) -> HassetteConfig:
    """Return a deep copy of ``config`` whose declaring app does or doesn't declare its switch."""
    config = config.model_copy(deep=True)
    [entry] = config.apps.apps.values()
    # app_entries (conftest) gives each app one instance, so its config is one mapping, not a list of instances.
    instance = entry.get("config")
    assert isinstance(instance, dict)
    entry["config"] = {**instance, "declare_switch": declare_switch}
    return config


@dataclass(frozen=True)
class DeclaredEntityIds:
    """The entity_ids HA gave the declaring app's entities, one field per key in DECLARED_KEYS."""

    presses: str
    ping: str
    occupied: str


def declared_entity_ids(entities: dict[str, dict[str, Any]], unique_ids: dict[str, str]) -> DeclaredEntityIds:
    """Look each declared entity's entity_id up in the entry's registry entries (keyed by unique_id)."""
    return DeclaredEntityIds(**{key: entities[unique_ids[key]]["entity_id"] for key in DECLARED_KEYS})


@dataclass(frozen=True)
class DeclaredInstance:
    """The declaring app's instance as HA registered it, which the startups after the first one check against."""

    app_key: str
    instance_name: str
    # Keyed by the declared key in DECLARED_KEYS.
    unique_ids: dict[str, str]
    entity_ids: DeclaredEntityIds


def declaring_instance(hassette: Hassette) -> tuple[str, str]:
    """The declaring app's app_key and its one instance's name."""
    [app_key] = hassette.app_handler.registry.app_keys()
    [instance_name] = hassette.app_handler.registry.configured_names(app_key)
    return app_key, instance_name


def declared_unique_ids(app_key: str, instance_name: str) -> dict[str, str]:
    """Each declared key's unique_id, in hass-hassette's ``{app_key}-{instance_name}-{key}`` format."""
    return {key: f"{app_key}-{instance_name}-{key}" for key in DECLARED_KEYS}


def declaring_app(hassette: Hassette, declared: DeclaredInstance) -> Any:
    """The running declaring app. Typed ``Any``: hassette loads it from its file, so its class isn't importable here."""
    return hassette.app_handler.registry.get(declared.app_key, declared.instance_name)


@pytest.mark.timeout(DECLARED_TEST_TIMEOUT_SECONDS)
async def test_declared_entities_survive_a_hassette_restart_and_follow_declarations(
    ha_container: str, tmp_path: Path
) -> None:
    """Declared entities sit on the instance's device, run its handlers and take pushed values; they keep their
    state across a hassette restart, and a declaration the instance drops is removed from HA.
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    config, base_url = make_web_system_config(ha_container, tmp_path, host="0.0.0.0", auth_token=token)
    # Every startup reuses this config's port, which the entry's URL names, and its data dir, which holds the
    # declared entities' state.
    config = with_app_entries(config, DECLARING_APP_DIR)
    hassette_url = f"http://{HOST_FROM_HA}:{config.web_api.port}"
    poll = {"timeout": POLL_TIMEOUT_SECONDS, "interval": HA_POLL_INTERVAL_SECONDS}
    push = {"timeout": PUSH_TIMEOUT_SECONDS, "interval": HA_POLL_INTERVAL_SECONDS}
    # The entry spans all three startups, so it's created inside the first and removed in the finally below.
    created_entries: list[str] = []

    async with ha_client(ha_container) as ha:

        async def declare_and_drive() -> DeclaredInstance:
            async with startup_context(config) as hassette:
                await wait_for_web_server(base_url)
                app_key, instance_name = declaring_instance(hassette)
                unique_ids = declared_unique_ids(app_key, instance_name)
                entry_id = await create_entry(ha, hassette_url, token)
                created_entries.append(entry_id)
                entities = await wait_for_app_entities(ha_container, entry_id, set(unique_ids.values()))
                declared = DeclaredInstance(
                    app_key=app_key,
                    instance_name=instance_name,
                    unique_ids=unique_ids,
                    entity_ids=declared_entity_ids(entities, unique_ids),
                )
                presses, ping, occupied = (
                    declared.entity_ids.presses,
                    declared.entity_ids.ping,
                    declared.entity_ids.occupied,
                )

                # Every declared entity sits on the instance's device, a child device (parent_device_id) of the app's.
                devices = {d["id"]: d for d in await ha_ws(ha_container, {"type": "config/device_registry/list"})}
                instance_device = devices[entities[unique_ids["presses"]]["device_id"]]
                assert [INTEGRATION, f"{app_key}-{instance_name}"] in instance_device["identifiers"]
                assert [INTEGRATION, app_key] in devices[instance_device["parent_device_id"]]["identifiers"]
                assert {entities[unique_id]["device_id"] for unique_id in unique_ids.values()} == {
                    instance_device["id"]
                }

                await call_service(ha, "button", "press", ping)
                await wait_for(state_is(ha, presses, "1"), desc="the press counted", **poll)
                await call_service(ha, "switch", "turn_on", occupied)
                await wait_for(state_is(ha, occupied, "on"), desc="the switch on", **poll)

                # A value the app sets on its own, with no HA action to trigger a refresh, arrives by push.
                await declaring_app(hassette, declared).presses.set(PUSHED_COUNT)
                await wait_for(state_is(ha, presses, str(PUSHED_COUNT)), desc="the pushed value", **push)
                return declared

        async def restart_with_state(declared: DeclaredInstance) -> None:
            presses, ping, occupied = (
                declared.entity_ids.presses,
                declared.entity_ids.ping,
                declared.entity_ids.occupied,
            )
            async with startup_context(config) as hassette:
                await wait_for_web_server(base_url)
                app = declaring_app(hassette, declared)
                assert app.presses.value == PUSHED_COUNT
                assert app.occupied.is_on
                # The entities may have gone unavailable while hassette was down, and HA skips an action on an
                # unavailable entity, so wait for HA to show the restored state before pressing.
                await wait_for(state_is(ha, presses, str(PUSHED_COUNT)), desc="the restored value in HA", **poll)
                await wait_for(state_is(ha, occupied, "on"), desc="the restored switch in HA", **poll)
                await call_service(ha, "button", "press", ping)
                await wait_for(state_is(ha, presses, str(PUSHED_COUNT + 1)), desc="the press after the restart", **poll)

        async def drop_the_switch(declared: DeclaredInstance) -> None:
            [entry_id] = created_entries
            async with startup_context(with_declare_switch(config, declare_switch=False)):
                await wait_for_web_server(base_url)

                async def switch_removed_sensor_kept() -> bool:
                    registered = await app_entities(ha_container, entry_id)
                    return declared.unique_ids["occupied"] not in registered and (
                        declared.unique_ids["presses"] in registered
                    )

                await wait_for(switch_removed_sensor_kept, desc="the switch removed and the sensor kept", **poll)
                # Removed while hassette still runs, so the session's HA isn't left polling a stopped server.
                await remove_entry(ha, created_entries.pop())

        try:
            declared = await in_own_context(declare_and_drive)
            await in_own_context(lambda: restart_with_state(declared))
            await in_own_context(lambda: drop_the_switch(declared))
        finally:
            for entry_id in created_entries:
                await remove_entry(ha, entry_id)


# Destructive: it restarts the session's HA. nox runs system_destructive tests in their own pass after the rest
# (noxfile.py's system sessions), so the other tests in this module never see HA mid-restart.
@pytest.mark.system_destructive
@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.timeout(DECLARED_TEST_TIMEOUT_SECONDS)
async def test_declared_entities_survive_a_home_assistant_restart(ha_container: str, tmp_path: Path) -> None:
    """After HA restarts, the integration shows the declared sensor's and switch's state hassette holds."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    config, base_url = make_web_system_config(ha_container, tmp_path, host="0.0.0.0", auth_token=token)
    config = with_app_entries(config, DECLARING_APP_DIR)
    poll = {"timeout": POLL_TIMEOUT_SECONDS, "interval": HA_POLL_INTERVAL_SECONDS}
    # An earlier destructive test may have just restarted HA.
    await asyncio.to_thread(wait_for_ha_ready)

    async with (
        startup_context(config) as hassette,
        ha_client(ha_container) as ha,
    ):
        await wait_for_web_server(base_url)
        unique_ids = declared_unique_ids(*declaring_instance(hassette))
        async with config_entry(ha, f"http://{HOST_FROM_HA}:{config.web_api.port}", token) as entry_id:
            entities = await wait_for_app_entities(ha_container, entry_id, set(unique_ids.values()))
            ids = declared_entity_ids(entities, unique_ids)
            presses, ping, occupied = ids.presses, ids.ping, ids.occupied
            await call_service(ha, "button", "press", ping)
            await call_service(ha, "switch", "turn_on", occupied)
            await wait_for(state_is(ha, presses, "1"), desc="the press counted", **poll)
            await wait_for(state_is(ha, occupied, "on"), desc="the switch on", **poll)

            # Off the event loop, so hassette keeps running while HA restarts.
            await asyncio.to_thread(subprocess.run, ["docker", "restart", HA_CONTAINER_NAME], check=True)
            await asyncio.to_thread(wait_for_ha_ready)

            await wait_for(state_is(ha, presses, "1"), desc="the sensor after the HA restart", **poll)
            await wait_for(state_is(ha, occupied, "on"), desc="the switch after the HA restart", **poll)
