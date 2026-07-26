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

from httpx2 import ASGITransport, AsyncClient, Response

from hassette import Hassette
from hassette.test_utils import wait_for
from hassette.test_utils.helpers import cleanup_hassette_streams
from hassette.web.app import create_fastapi_app

WEBAPI_READY_TIMEOUT = 10.0
HEALTH_ENDPOINT = "/api/health"


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
    # lazy-import: a module-level import makes pytest try to collect TestConfig as a test class
    from tests.conftest import TEST_APPS_PATH, TestConfig

    config = TestConfig(
        data_dir=tmp_path / "data",
        web_api={"run": True, "port": unused_tcp_port_factory()},
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
        """WebApiService reaches ready, apps bootstrap, and /api/health serves 200 without HA."""
        async with _running_hassette_without_ha(tmp_path, unused_tcp_port_factory) as hassette:
            assert hassette._web_api_service is not None
            assert hassette._web_api_service.is_ready()

            snapshot = hassette.app_handler.registry.get_full_snapshot()
            assert snapshot.total >= 1
            assert any(manifest.app_key == "my_app" for manifest in snapshot.manifests)

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
