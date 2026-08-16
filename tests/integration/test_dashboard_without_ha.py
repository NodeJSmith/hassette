"""Integration tests: the dashboard serves and reports accurate status when HA is unreachable.

These tests boot a real Hassette instance (real wave-based startup, real AppHandler,
real WebApiService) with WebsocketService's ``serve()`` replaced by a coroutine that never
completes, so the WebSocket connection never reaches CONNECTED. This exercises the actual
dependency-decoupling fix end-to-end: WebApiService must still reach ready and serve HTTP,
apps must still bootstrap, and the health endpoint must report "starting" rather than hanging
or tearing down the process.

See design/specs/018-dashboard-without-ha/design.md for the full rationale.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx2 import ASGITransport, AsyncClient, Response

from hassette import Hassette
from hassette.test_utils import make_light_state_dict, wait_for
from hassette.test_utils.config import TEST_TOTAL_TIMEOUT_SECONDS
from hassette.test_utils.helpers import cleanup_hassette_streams
from hassette.types.enums import ConnectionState
from hassette.web.app import create_fastapi_app

WEBAPI_READY_TIMEOUT = 10.0
HEALTH_ENDPOINT = "/api/health"
STATE_READER_APP = """
from hassette import App, AppConfig


class StateReaderConfig(AppConfig):
    test_entity: str = "light.office"


class StateReaderApp(App[StateReaderConfig]):
    async def on_initialize(self) -> None:
        self.states.light[self.app_config.test_entity]
""".strip()


async def _get_health(hassette: Hassette) -> Response:
    transport = ASGITransport(app=create_fastapi_app(hassette))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(HEALTH_ENDPOINT)


@contextlib.asynccontextmanager
async def _running_hassette_without_ha(
    tmp_path: Path, unused_tcp_port_factory: Callable[[], int]
) -> AsyncIterator[Hassette]:
    """Boot a real Hassette instance whose WebsocketService never connects.

    ``StateProxy.load_cache()`` is short-circuited (``hassette.api.get_states_raw`` raises
    immediately) instead of letting the real retry/backoff run against an unreachable HA —
    that boundary-level patch is the same pattern ``tests/integration/test_state_proxy.py``
    uses, and it keeps this test fast and deterministic. ``WebsocketService.serve()`` is
    replaced with a coroutine that awaits an ``asyncio.Event`` that is never set, so the
    connection state stays DISCONNECTED and ``has_ever_connected`` stays False for the
    lifetime of the test.
    """
    # house-lint: ignore-next[HSL002] - a module-level import makes pytest try to collect TestConfig as a test class
    from tests.conftest import TEST_APPS_PATH, TestConfig

    config = TestConfig(
        data_dir=tmp_path / "data",
        # auth_enabled=False + a loopback host: this test hits /api/health with no credential via
        # `_get_health()`, and auth is on by default now that the default-deny middleware actually
        # enforces it. Pinning host to loopback alongside disabling auth matches the project's
        # startup guard (a non-loopback host with auth disabled refuses to start).
        web_api={"run": True, "port": unused_tcp_port_factory(), "auth_enabled": False, "host": "127.0.0.1"},
        websocket={"total_timeout_seconds": TEST_TOTAL_TIMEOUT_SECONDS},
        apps={
            "directory": TEST_APPS_PATH,
            "autodetect": False,
            "apps": {
                # my_app skips its on_initialize() body under pytest (checks PYTEST_VERSION),
                # so it bootstraps instantly without touching HA — unlike my_app_sync, which
                # would hit the real REST retry/backoff path and slow this test down.
                "my_app": {
                    "filename": "my_app.py",
                    "class_name": "MyApp",
                    "config": {"test_entity": "input_button.test", "instance_name": "unique_instance_name"},
                },
            },
        },
    )

    hassette = Hassette(config)
    hassette.wire_services()

    never_connects = asyncio.Event()

    async def hang_serve() -> None:
        await never_connects.wait()

    hassette.websocket_service.serve = hang_serve  # pyright: ignore[reportAttributeAccessIssue]
    hassette.api.get_states_raw = AsyncMock(side_effect=RuntimeError("HA unreachable in test"))

    run_task = asyncio.create_task(hassette.run_forever())
    try:
        await wait_for(
            lambda: hassette._web_api_service is not None and hassette._web_api_service.is_ready(),
            timeout=WEBAPI_READY_TIMEOUT,
            desc="WebApiService ready",
        )
        yield hassette
    finally:
        hassette.shutdown_event.set()
        never_connects.set()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(run_task, timeout=WEBAPI_READY_TIMEOUT)
        await cleanup_hassette_streams(hassette)


class TestDashboardWithoutHA:
    async def test_webapi_ready_without_ha_connection(
        self, tmp_path: Path, unused_tcp_port_factory: Callable[[], int]
    ) -> None:
        """WebApiService reaches ready and /api/health serves 200 while no app instance bootstraps.

        AppBootstrapCoordinator keeps app bootstrap blocked until Home Assistant reaches
        external WebSocket readiness. Registry metadata (manifests) is still queryable
        pre-bootstrap, but no live app instance may exist while the connection never
        succeeds — the web API's independence from Home Assistant is exactly the property
        under test here.
        """
        async with _running_hassette_without_ha(tmp_path, unused_tcp_port_factory) as hassette:
            assert hassette._web_api_service is not None
            assert hassette._web_api_service.is_ready()

            snapshot = hassette.app_handler.registry.get_full_snapshot()
            assert snapshot.total >= 1
            assert any(manifest.app_key == "my_app" for manifest in snapshot.manifests)

            # Registry metadata is queryable, but no app instance has bootstrapped.
            assert hassette.app_handler.has_bootstrapped() is False
            assert hassette.app_handler.get("my_app", 0) is None
            assert hassette.app_handler.all() == []
            assert hassette.app_bootstrap_coordinator.is_released() is False

            response = await _get_health(hassette)

            assert response.status_code == 200

    async def test_health_shows_starting_when_ws_never_connected(
        self, tmp_path: Path, unused_tcp_port_factory: Callable[[], int]
    ) -> None:
        """/api/health reports status 'starting' and websocket_connected False when WS never connects."""
        async with _running_hassette_without_ha(tmp_path, unused_tcp_port_factory) as hassette:
            status = hassette.runtime_query_service.get_system_status()
            assert status.status == "starting"
            assert status.websocket_connected is False

            response = await _get_health(hassette)

            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "starting"
            assert body["websocket_connected"] is False


class TestInitialStateSyncBeforeApps:
    async def test_app_bootstrap_waits_for_first_websocket_connection_and_state_sync(
        self, tmp_path: Path, unused_tcp_port_factory: Callable[[], int]
    ) -> None:
        """Apps that read startup state must not initialize against the optional-HA empty cold cache."""
        # house-lint: ignore-next[HSL002] - a module-level import makes pytest try to collect TestConfig as a test class
        from tests.conftest import TestConfig

        app_dir = tmp_path / "apps"
        app_dir.mkdir()
        (app_dir / "state_reader.py").write_text(STATE_READER_APP, encoding="utf-8")

        config = TestConfig(
            data_dir=tmp_path / "data",
            web_api={"run": True, "port": unused_tcp_port_factory()},
            # Must stay well above this test's own real-time hold further down (the
            # asyncio.wait_for(..., timeout=1) wrapped in pytest.raises(TimeoutError), just before
            # release_connection.set() is called) or StateProxy._bootstrap_initial_sync gives up on
            # the connection before that release fires — this raced and flaked under CI scheduling
            # jitter at 2s. See CLAUDE.md's "Config-driven real-clock timeouts" pattern.
            websocket={"total_timeout_seconds": TEST_TOTAL_TIMEOUT_SECONDS},
            apps={
                "directory": app_dir,
                "autodetect": False,
                "apps": {
                    "state_reader": {
                        "filename": "state_reader.py",
                        "class_name": "StateReaderApp",
                        "config": {"instance_name": "state_reader", "test_entity": "light.office"},
                    },
                },
            },
        )

        hassette = Hassette(config)
        hassette.wire_services()

        connection_attempted = asyncio.Event()
        release_connection = asyncio.Event()
        keep_ws_alive = asyncio.Event()
        state_proxy_subscribed = asyncio.Event()
        load_cache_entered = asyncio.Event()

        async def delayed_serve() -> None:
            hassette.websocket_service.set_connection_state(ConnectionState.CONNECTING)
            connection_attempted.set()
            await release_connection.wait()
            hassette.websocket_service._connected_generation = 1  # pyright: ignore[reportPrivateUsage]  # test-only readiness simulation
            hassette.websocket_service.set_connection_state(ConnectionState.CONNECTED)
            await hassette.websocket_service.send_connection_established_event()
            hassette.websocket_service._connected_event.set()  # pyright: ignore[reportPrivateUsage]  # coordinator-internal
            hassette.websocket_service._first_connection_attempt_done_event.set()  # pyright: ignore[reportPrivateUsage]  # coordinator-internal
            await keep_ws_alive.wait()

        async def load_states() -> list[dict]:
            load_cache_entered.set()
            return [make_light_state_dict("light.office", "on")]

        hassette.websocket_service.serve = delayed_serve  # pyright: ignore[reportAttributeAccessIssue]
        hassette.api.get_states_raw = AsyncMock(side_effect=load_states)
        original_subscribe_to_events = hassette.state_proxy.subscribe_to_events

        async def tracked_subscribe_to_events() -> None:
            await original_subscribe_to_events()
            state_proxy_subscribed.set()

        hassette.state_proxy.subscribe_to_events = tracked_subscribe_to_events  # pyright: ignore[reportAttributeAccessIssue]

        run_task = asyncio.create_task(hassette.run_forever())
        try:
            await asyncio.wait_for(connection_attempted.wait(), timeout=5)
            await asyncio.wait_for(state_proxy_subscribed.wait(), timeout=5)

            with pytest.raises(TimeoutError):
                await asyncio.wait_for(load_cache_entered.wait(), timeout=1)
            assert hassette.app_handler.registry.get("state_reader", 0) is None

            release_connection.set()

            await wait_for(
                lambda: ((app := hassette.app_handler.registry.get("state_reader", 0)) is not None and app.is_ready()),
                timeout=WEBAPI_READY_TIMEOUT,
                desc="state-reading app ready",
            )
            await asyncio.wait_for(load_cache_entered.wait(), timeout=5)
            hassette.api.get_states_raw.assert_awaited_once()

            app = hassette.app_handler.registry.get("state_reader", 0)
            assert app is not None
            assert app.is_ready()
        finally:
            hassette.shutdown_event.set()
            release_connection.set()
            keep_ws_alive.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(run_task, timeout=WEBAPI_READY_TIMEOUT)
            await cleanup_hassette_streams(hassette)
