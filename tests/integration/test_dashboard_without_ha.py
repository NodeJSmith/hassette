"""Integration tests: the dashboard serves and reports accurate status when HA is unreachable.

These tests boot a real Hassette instance (real wave-based startup, real AppHandler,
real WebApiService) with WebsocketService's ``serve()`` replaced by a coroutine that never
completes, so the WebSocket connection never reaches CONNECTED. This exercises the actual
dependency-decoupling fix end-to-end: WebApiService must still reach ready and serve HTTP,
apps must still bootstrap, and the health endpoint must report "starting" rather than hanging
or tearing down the process.

The same boot also covers a ``trusted_proxies`` hostname that doesn't resolve yet: the web API
must still start, trusting no peer for that entry until a refresh tick resolves it.

The same boot also covers the opposite case: when the web API's port is already taken, the
bind failure must tear the process down through Hassette's own shutdown and finalize the
session as 'failure', instead of uvicorn's sys.exit(1) ending it with no teardown.

See design/specs/018-dashboard-without-ha/design.md for the full rationale.
"""

import asyncio
import contextlib
import socket
import sqlite3
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx2 import ASGITransport, AsyncClient, Response

from hassette import Hassette
from hassette import context as hassette_context
from hassette.core.session_manager import SESSION_STATUS_FAILURE
from hassette.exceptions import FatalError
from hassette.testing import make_light_state_dict, wait_for
from hassette.types.enums import ConnectionState
from hassette.web.app import create_fastapi_app
from tests.support.helpers import cleanup_hassette_streams, make_addrinfo, patch_loop_getaddrinfo
from tests.support.mock_hassette import TEST_TOTAL_TIMEOUT_SECONDS

WEBAPI_READY_TIMEOUT = 10.0
STARTUP_EVENT_TIMEOUT = 5
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


async def _teardown_bare_hassette(
    hassette: Hassette,
    run_task: asyncio.Task,
    loop: asyncio.AbstractEventLoop,
    *,
    previous_task_factory: object,
    instance_token: object,
) -> None:
    """Shut down a manually-wired Hassette instance and restore loop/context state.

    Shared by this module's two call sites that construct a bare Hassette (bypassing the
    harness) and drive it via ``run_forever()``. Order matters: restore the task factory
    before anything below (including ``cleanup_hassette_streams``'s internal task creation)
    that might create a new Task on this session-scoped loop — ``run_forever()`` installs a
    TaskBucket-routing factory that seals once shutdown completes. Callers must set their own
    unblocking events (e.g. a hung ``serve()``'s wait event) before calling this.

    The restore/cleanup below runs in a ``finally`` block: ``suppress(Exception)`` around the
    wait for ``run_task`` does not catch ``asyncio.CancelledError`` (a ``BaseException``), so a
    cancellation delivered to *this* coroutine while awaiting ``run_task`` would otherwise skip
    the task-factory restore and instance-token reset entirely. Since the loop is session-scoped,
    a poisoned task factory or a stale global Hassette reference would then affect every later
    test on the same worker, not just this one. The instance-token reset gets its own nested
    ``finally`` around ``cleanup_hassette_streams`` for the same reason: a cancellation delivered
    specifically during that await would otherwise propagate past its own ``suppress(Exception)``
    (again, ``CancelledError`` is a ``BaseException``) and skip the reset below it.
    """
    hassette.shutdown_event.set()
    try:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(run_task, timeout=WEBAPI_READY_TIMEOUT)
    finally:
        loop.set_task_factory(previous_task_factory)  # pyright: ignore[reportArgumentType]
        try:
            with contextlib.suppress(Exception):
                await cleanup_hassette_streams(hassette)
        finally:
            if instance_token is not None:
                hassette_context.HASSETTE_INSTANCE.reset(instance_token)  # pyright: ignore[reportArgumentType]


def _wire_hassette_without_ha(
    tmp_path: Path, port: int, **web_api_overrides: Any
) -> tuple[Hassette, asyncio.Event, object]:
    """Build and wire a real Hassette instance whose WebsocketService never connects.

    ``StateProxy.load_cache()`` is short-circuited (``hassette.api.get_states_raw`` raises
    immediately) instead of letting the real retry/backoff run against an unreachable HA —
    that boundary-level patch is the same pattern ``tests/integration/test_state_proxy.py``
    uses, and it keeps these tests fast and deterministic. ``WebsocketService.serve()`` is
    replaced with a coroutine that awaits the returned ``asyncio.Event``, so the connection
    state stays DISCONNECTED and ``has_ever_connected`` stays False until the caller sets it.

    ``web_api_overrides`` replace keys of the default ``web_api`` config below.

    Returns the instance, that event, and the ``HASSETTE_INSTANCE`` token to reset on teardown.
    """
    # house-lint: ignore-next[HSL002] - a module-level import makes pytest try to collect TestConfig as a test class
    from tests.conftest import TEST_APPS_PATH, TestConfig

    config = TestConfig(
        data_dir=tmp_path / "data",
        # auth_enabled=False + a loopback host: this test hits /api/health with no credential via
        # `_get_health()`, and auth is on by default now that the default-deny middleware actually
        # enforces it. Pinning host to loopback alongside disabling auth matches the project's
        # startup guard (a non-loopback host with auth disabled refuses to start).
        web_api={"run": True, "port": port, "auth_enabled": False, "host": "127.0.0.1", **web_api_overrides},
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
    # wire_services() calls context.set_global_hassette(hassette) internally and does not
    # expose the returned Token, so set it ourselves first to capture the Token — wire_services()'s
    # own call then early-returns None (same instance already set) and is a no-op. Callers run
    # setup and teardown in the same coroutine/Context (unlike a pytest-asyncio generator
    # fixture), so resetting a manually-captured Token in their teardown is valid — see
    # tests/integration/conftest.py's hassette_instance docstring for why that would NOT be true
    # across a fixture setup/teardown boundary.
    instance_token = hassette_context.set_global_hassette(hassette)
    hassette.wire_services()

    never_connects = asyncio.Event()

    async def hang_serve() -> None:
        await never_connects.wait()

    hassette.websocket_service.serve = hang_serve  # pyright: ignore[reportAttributeAccessIssue]
    hassette.api.get_states_raw = AsyncMock(side_effect=RuntimeError("HA unreachable in test"))
    return hassette, never_connects, instance_token


@contextlib.asynccontextmanager
async def _running_hassette_without_ha(
    tmp_path: Path, unused_tcp_port_factory: Callable[[], int], **web_api_overrides: Any
) -> AsyncIterator[Hassette]:
    """Boot a real Hassette instance whose WebsocketService never connects (see ``_wire_hassette_without_ha``)."""
    loop = asyncio.get_running_loop()
    previous_task_factory = loop.get_task_factory()
    hassette, never_connects, instance_token = _wire_hassette_without_ha(
        tmp_path, unused_tcp_port_factory(), **web_api_overrides
    )

    run_task = asyncio.create_task(hassette.run_forever())
    try:
        await wait_for(
            lambda: hassette._web_api_service is not None and hassette._web_api_service.is_ready(),
            timeout=WEBAPI_READY_TIMEOUT,
            desc="WebApiService ready",
        )
        yield hassette
    finally:
        never_connects.set()
        await _teardown_bare_hassette(
            hassette, run_task, loop, previous_task_factory=previous_task_factory, instance_token=instance_token
        )


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


class TestUnresolvableTrustedProxyHostname:
    async def test_startup_serves_and_refresh_trusts_hostname_once_it_resolves(
        self, tmp_path: Path, unused_tcp_port_factory: Callable[[], int]
    ) -> None:
        """A trusted_proxies hostname that misses DNS at startup no longer fails the web API.

        The entry trusts no peer until it resolves; the scheduled refresh job then trusts it with
        no restart.
        """
        with patch_loop_getaddrinfo(side_effect=socket.gaierror("Name or service not known")):
            async with _running_hassette_without_ha(
                tmp_path, unused_tcp_port_factory, auth_enabled=True, trusted_proxies=("caddy",)
            ) as hassette:
                service = hassette._web_api_service
                assert service is not None
                await wait_for(lambda: service._app is not None, timeout=WEBAPI_READY_TIMEOUT, desc="app built")
                live_app = service._app
                assert live_app is not None

                transport = ASGITransport(app=live_app, client=("172.30.32.2", 12345))
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    assert (await client.get("/api/health/live")).status_code == 200
                    assert (await client.get("/api/config")).status_code == 401

                    with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.2")]):
                        await service._refresh_trusted_proxies()

                    assert (await client.get("/api/config")).status_code == 200


class TestWebApiPortInUse:
    async def test_port_in_use_tears_down_and_finalizes_session_as_failure(
        self, tmp_path: Path, unused_tcp_port_factory: Callable[[], int]
    ) -> None:
        """A web API bind failure goes through Hassette's teardown instead of uvicorn's sys.exit.

        run_forever() must raise FatalError (not SystemExit) after a full shutdown, and the
        session row must be finalized as 'failure' rather than left 'running'.
        """
        port = unused_tcp_port_factory()
        loop = asyncio.get_running_loop()
        previous_task_factory = loop.get_task_factory()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.bind(("127.0.0.1", port))
            holder.listen()

            hassette, never_connects, instance_token = _wire_hassette_without_ha(tmp_path, port)
            run_task = asyncio.create_task(hassette.run_forever())
            try:
                with pytest.raises(FatalError):
                    await asyncio.wait_for(run_task, timeout=WEBAPI_READY_TIMEOUT)
            finally:
                never_connects.set()
                await _teardown_bare_hassette(
                    hassette, run_task, loop, previous_task_factory=previous_task_factory, instance_token=instance_token
                )

        with contextlib.closing(sqlite3.connect(hassette.database_service.resolve_db_path())) as conn:
            rows = conn.execute("SELECT status, stopped_at, error_message FROM sessions").fetchall()

        assert len(rows) == 1
        status, stopped_at, error_message = rows[0]
        assert status == SESSION_STATUS_FAILURE
        assert stopped_at is not None
        assert f"127.0.0.1:{port}" in error_message


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
        loop = asyncio.get_running_loop()
        previous_task_factory = loop.get_task_factory()
        # See _running_hassette_without_ha's comment above for why capturing our own Token here
        # (instead of relying on wire_services()'s internal, unexposed set_global_hassette() call)
        # is both necessary and valid in this plain-coroutine test body.
        instance_token = hassette_context.set_global_hassette(hassette)
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
            # Mirrors mark_connected(): notifying connected observers starts StateProxy's initial sync.
            await hassette.websocket_service.connected_observers.notify(1)
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
            await asyncio.wait_for(connection_attempted.wait(), timeout=STARTUP_EVENT_TIMEOUT)
            await asyncio.wait_for(state_proxy_subscribed.wait(), timeout=STARTUP_EVENT_TIMEOUT)

            with pytest.raises(TimeoutError):
                await asyncio.wait_for(load_cache_entered.wait(), timeout=1)
            assert hassette.app_handler.registry.get("state_reader", 0) is None

            release_connection.set()

            await wait_for(
                lambda: (app := hassette.app_handler.registry.get("state_reader", 0)) is not None and app.is_ready(),
                timeout=WEBAPI_READY_TIMEOUT,
                desc="state-reading app ready",
            )
            await asyncio.wait_for(load_cache_entered.wait(), timeout=STARTUP_EVENT_TIMEOUT)
            hassette.api.get_states_raw.assert_awaited_once()

            app = hassette.app_handler.registry.get("state_reader", 0)
            assert app is not None
            assert app.is_ready()
        finally:
            release_connection.set()
            keep_ws_alive.set()
            await _teardown_bare_hassette(
                hassette, run_task, loop, previous_task_factory=previous_task_factory, instance_token=instance_token
            )
