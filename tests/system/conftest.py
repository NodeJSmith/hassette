"""System test fixtures."""

import asyncio
import contextlib
import json
import logging
import os
import shutil
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic_settings import SettingsConfigDict

from hassette import Hassette
from hassette.api import Api
from hassette.bus import Bus
from hassette.config.config import HassetteConfig
from hassette.events import RawStateChangeEvent
from hassette.test_utils import wait_for

logger = logging.getLogger(__name__)

COMPOSE_FILE = Path(__file__).parent / "docker-compose.yml"
FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "ha-config"
HA_URL = "http://localhost:18123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMyIsImlhdCI6MTczNTY4OTYwMCwiZXhwIjoyMDUxMDQ5NjAwfQ.q-p85dOe-MMnKQhSNh_LEWnWJGK-GA3xdmqb4LKvkU0"  # noqa: E501 — JWT cannot be line-wrapped
HA_CONTAINER_NAME = "hassette-system-ha"
STARTUP_TIMEOUT = 60  # seconds
SHUTDOWN_TIMEOUT = 15  # seconds


class _SystemTestConfig(HassetteConfig):
    """HassetteConfig subclass that disables CLI arg parsing for system tests."""

    model_config = HassetteConfig.model_config.copy() | SettingsConfigDict(
        cli_parse_args=False,
        env_file=None,
        toml_file=None,
    )

    def model_post_init(self, *args):
        # Skip default overrides applied in production config.
        pass


@pytest.fixture(scope="session")
def ha_container(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start the HA Docker container for the test session and tear it down after.

    Copies the committed fixture files to a temporary directory before starting
    the container, so HA's writes (log files, updated .storage/ entries) never
    pollute the repository working tree.

    Yields the base URL for the running Home Assistant instance.
    """
    # Copy only the committed fixture files — skip HA runtime artifacts.
    # This prevents root-owned files from previous container runs from
    # polluting the copy and causing PermissionError.
    _ignore = shutil.ignore_patterns(
        ".HA_VERSION",
        "home-assistant.log*",
        "known_devices.yaml",
        "blueprints",
        "core.area_registry",
        "core.device_registry",
        "core.entity_registry",
        "core.restore_state",
        "homeassistant.exposed_entities",
        "http",
        "http.auth",
        "person",
        "repairs.issue_registry",
        "trace.saved_traces",
    )
    config_tmp = tmp_path_factory.mktemp("ha-config", numbered=False)
    shutil.copytree(FIXTURE_DIR, config_tmp, dirs_exist_ok=True, ignore=_ignore)

    env = {**os.environ, "HA_CONFIG_PATH": str(config_tmp)}
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "homeassistant"],
        check=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            try:
                r = httpx.get(
                    f"{HA_URL}/api/",
                    headers={"Authorization": f"Bearer {HA_TOKEN}"},
                    timeout=3,
                )
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            pytest.fail(f"HA did not become ready within {STARTUP_TIMEOUT}s")

        yield HA_URL
    finally:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down"],
            check=False,
            env=env,
        )


def _session_ready(hassette: Hassette) -> bool:
    """Check if Hassette has a valid session and the WebSocket is fully ready.

    session_id > 0 becomes true after Phase 1 (database + session creation).
    is_ready() now fires only after authentication AND event subscriptions
    complete, so no private field access is needed.
    """
    try:
        return hassette.session_id > 0 and hassette.websocket_service.is_ready()
    except Exception:
        return False


@asynccontextmanager
async def startup_context(config: HassetteConfig, timeout: int = 30) -> AsyncIterator[Hassette]:
    """Run Hassette.run_forever() in a background task until ready, then yield for assertions.

    Args:
        config: The HassetteConfig to use when constructing the Hassette instance.
        timeout: Maximum seconds to wait for Hassette to reach a running state.

    Yields:
        The running Hassette instance.

    Raises:
        TimeoutError: If Hassette does not reach running state within ``timeout`` seconds.
    """
    hassette = Hassette(config)
    hassette.wire_services()
    task = asyncio.create_task(hassette.run_forever())
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not _session_ready(hassette):
            if task.done():
                await task  # re-raises any startup exception immediately
                raise RuntimeError("Hassette exited during startup without reaching running state")
            if loop.time() > deadline:
                task.cancel()
                raise TimeoutError(f"Hassette did not reach running state within {timeout}s")
            await asyncio.sleep(0.1)
        yield hassette
    finally:
        hassette.shutdown_event.set()
        try:
            await asyncio.wait_for(task, timeout=SHUTDOWN_TIMEOUT)
        except asyncio.CancelledError:
            pass
        except TimeoutError:
            logger.warning("Hassette shutdown timed out after 15s — forcing fallback")
        if not hassette._shutdown_completed:
            with contextlib.suppress(Exception):
                await hassette.shutdown()


def make_system_config(ha_url: str, tmp_path: Path) -> HassetteConfig:
    """Build a minimal HassetteConfig pointing at the system test HA container.

    Args:
        ha_url: Base URL of the running Home Assistant instance.
        tmp_path: Per-test temporary directory used for ``data_dir`` and ``app_dir``.

    Returns:
        A configured HassetteConfig instance.
    """
    app_dir = tmp_path / "apps"
    app_dir.mkdir(exist_ok=True)

    return _SystemTestConfig(
        base_url=ha_url,
        token=HA_TOKEN,
        data_dir=tmp_path / "data",
        app_dir=app_dir,
        run_web_api=False,
        autodetect_apps=False,
        startup_timeout_seconds=30,
    )


def make_web_system_config(ha_url: str, tmp_path: Path) -> tuple[HassetteConfig, str]:
    """Build a HassetteConfig with the web API enabled, using a dynamically assigned port.

    Finds a free port by binding a socket, releases it, then uses that port for the
    web API. This avoids port conflicts between parallel test runs.

    Args:
        ha_url: Base URL of the running Home Assistant instance.
        tmp_path: Per-test temporary directory used for ``data_dir`` and ``app_dir``.

    Returns:
        A tuple of ``(config, base_url)`` where ``base_url`` is e.g.
        ``http://localhost:PORT``.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 0))
        port = sock.getsockname()[1]

    app_dir = tmp_path / "apps"
    app_dir.mkdir(exist_ok=True)

    config = _SystemTestConfig(
        base_url=ha_url,
        token=HA_TOKEN,
        data_dir=tmp_path / "data",
        app_dir=app_dir,
        run_web_api=True,
        web_api_port=port,
        autodetect_apps=False,
        startup_timeout_seconds=30,
    )
    return config, f"http://127.0.0.1:{port}"


async def toggle_and_capture(
    bus: Bus,
    api: Api,
    entity_id: str,
    *,
    service_domain: str = "light",
    service_action: str = "toggle",
    timeout: float = 10.0,
) -> list[RawStateChangeEvent]:
    """Register a state-change handler, toggle an entity, and wait for at least one event.

    Registers a ``bus.on_state_change`` handler for ``entity_id``, calls
    ``api.call_service`` to trigger the given service, then waits (via
    ``wait_for``) until at least one event is captured.

    Args:
        bus: The Bus instance to subscribe on.
        api: The Api instance to call the service through.
        entity_id: The entity ID to watch and toggle (e.g. ``"light.kitchen_lights"``).
        service_domain: The HA service domain (default ``"light"``).
        service_action: The HA service action (default ``"toggle"``).
        timeout: Maximum seconds to wait for an event to arrive (default 10.0).

    Returns:
        The list of captured ``RawStateChangeEvent`` objects (at least one).
    """
    captured: list[RawStateChangeEvent] = []

    async def _handler(event: RawStateChangeEvent) -> None:
        captured.append(event)

    sub = bus.on_state_change(entity_id, handler=_handler)
    await wait_for(
        lambda: sub.listener.db_id is not None,
        timeout=10.0,
        desc=f"listener registration for {entity_id}",
    )
    await api.call_service(service_domain, service_action, {"entity_id": entity_id})
    await wait_for(lambda: len(captured) >= 1, timeout=timeout, desc=f"state_changed event for {entity_id}")
    return captured


async def wait_for_web_server(base_url: str, *, timeout: float = 30.0) -> None:
    """Poll the health endpoint until the web server responds.

    The uvicorn server starts asynchronously alongside Hassette's other services;
    it may take a second or two before it accepts connections.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    last_exc: Exception | None = None
    async with httpx.AsyncClient() as client:
        while asyncio.get_running_loop().time() < deadline:
            try:
                r = await client.get(f"{base_url}/api/health", timeout=2.0)
                if r.status_code in (200, 503):
                    return
            except Exception as exc:
                last_exc = exc
            await asyncio.sleep(0.2)
    raise TimeoutError(f"Web server at {base_url} did not start within {timeout}s: {last_exc}")


def wait_for_ha_ready(base_url: str = HA_URL, *, timeout: float = 60.0, stable_checks: int = 3) -> None:
    """Block until HA's REST API responds 200 consistently and a WebSocket handshake succeeds.

    A single REST 200 is not sufficient — after a docker restart, HA may
    accept REST requests while its WebSocket handler is still initializing,
    causing connections to drop ~10s later. This function requires consecutive
    REST successes, then verifies a WebSocket can connect and authenticate.
    """
    deadline = time.monotonic() + timeout

    # Phase 1: consecutive REST checks
    consecutive = 0
    while time.monotonic() < deadline:
        try:
            r = httpx.get(
                f"{base_url}/api/",
                headers={"Authorization": f"Bearer {HA_TOKEN}"},
                timeout=3,
            )
            if r.status_code == 200:
                consecutive += 1
                if consecutive >= stable_checks:
                    break
            else:
                consecutive = 0
        except Exception:
            consecutive = 0
        time.sleep(1)
    else:
        raise TimeoutError(f"HA REST API did not stabilize within {timeout}s")

    # Phase 2: verify WebSocket connects, authenticates, and stays open briefly.
    # HA may accept the WS handshake but drop it seconds later while still
    # initializing — holding the connection for a few seconds catches this.
    ws_url = base_url.replace("http", "ws") + "/api/websocket"
    while time.monotonic() < deadline:
        try:
            _ws_probe(ws_url, hold_seconds=3)
            return
        except Exception:
            time.sleep(1)
    raise TimeoutError(f"HA WebSocket did not stabilize within {timeout}s")


def _ws_probe(ws_url: str, hold_seconds: float = 3) -> None:
    """Open a WebSocket, authenticate, hold for ``hold_seconds``, then close.

    Raises on any failure — connection refused, auth rejected, or HA dropping
    the connection during the hold window. Uses the synchronous websockets
    client to avoid conflicts with the test's running event loop.
    """
    from websockets.sync.client import connect

    with connect(ws_url) as ws:
        msg = json.loads(ws.recv(timeout=5))
        assert msg["type"] == "auth_required"
        ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        msg = json.loads(ws.recv(timeout=5))
        if msg["type"] != "auth_ok":
            raise RuntimeError(f"WS auth failed: {msg}")
        time.sleep(hold_seconds)


@pytest.fixture(scope="session")
def system_app_dir() -> Path:
    """Return the directory containing system test app fixtures.

    Returns:
        Path to ``tests/system/apps/``.
    """
    return Path(__file__).parent / "apps"
