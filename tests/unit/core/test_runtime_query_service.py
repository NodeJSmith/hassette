"""Unit tests for RuntimeQueryService."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock

import pytest

from hassette.core.app_handler import AppHandler
from hassette.core.app_registry import AppRegistry
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.events.hassette import (
    HassetteExecutionCompletedEvent,
    HassetteServiceEvent,
)
from hassette.schemas.app_snapshots import AppFullSnapshot, AppStatusSnapshot
from hassette.schemas.domain_models import SystemStatus
from hassette.test_utils import create_app_manifest
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.test_utils.web_manifest_helpers import make_app_instance_info, make_manifest_db_row
from hassette.types.enums import BlockReason, ResourceRole, ResourceStatus

WS_QUEUE_MAX = 256


async def assert_flushed_single_message(
    runtime: RuntimeQueryService, broadcast_calls: list[dict], expected_entries: int = 2
) -> dict:
    """Flush pending completions and assert exactly one batched execution_completed message."""
    await runtime.flush_completions()

    assert len(broadcast_calls) == 1
    msg = broadcast_calls[0]
    assert msg["type"] == "execution_completed"
    assert len(msg["data"]) == expected_entries
    return msg


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance with required attributes."""
    hassette = make_mock_hassette(
        sealed=False,
        web_api={"run": True},
        lifecycle={"startup_timeout_seconds": 5},
    )

    # Wire public properties to private mocks
    hassette.state_proxy = hassette._state_proxy
    hassette.websocket_service = hassette._websocket_service
    hassette.app_handler = hassette._app_handler
    hassette.bus_service = hassette._bus_service
    hassette.scheduler_service = hassette._scheduler_service
    hassette.runtime_query_service = hassette._runtime_query_service

    # The log health helpers are synchronous; replace AsyncMock with Mock
    hassette.get_log_queue_drops = Mock(return_value=0)
    hassette.get_db_write_queue_drops = Mock(return_value=0)
    hassette.is_log_persistence_active = Mock(return_value=True)

    # Mock state proxy
    hassette._state_proxy.states = {
        "light.kitchen": {
            "entity_id": "light.kitchen",
            "state": "on",
            "attributes": {"brightness": 255},
            "last_changed": "2024-01-01T00:00:00",
            "last_updated": "2024-01-01T00:00:00",
        },
        "sensor.temp": {
            "entity_id": "sensor.temp",
            "state": "21.5",
            "attributes": {"unit_of_measurement": "°C"},
            "last_changed": "2024-01-01T00:00:00",
            "last_updated": "2024-01-01T00:00:00",
        },
    }
    hassette._state_proxy.is_ready = Mock(return_value=True)

    # Mock websocket service — is_ready() is synchronous; replace AsyncMock with Mock
    hassette._websocket_service.status = ResourceStatus.RUNNING
    hassette._websocket_service.is_ready = Mock(return_value=True)

    # Mock app handler — sync methods need explicit Mock (parent is AsyncMock)
    instance = make_app_instance_info(app_key="my_app")
    hassette._app_handler.get_status_snapshot = Mock(return_value=AppStatusSnapshot(instances=[instance]))
    hassette._app_handler.registry.get_full_snapshot = Mock(return_value=AppFullSnapshot(manifests=[]))

    # Mock scheduler service
    hassette._scheduler_service.get_all_jobs = AsyncMock(return_value=[])

    return hassette


@pytest.fixture
def runtime(mock_hassette):
    """Create a RuntimeQueryService instance with mocked Hassette."""
    svc = RuntimeQueryService.__new__(RuntimeQueryService)
    svc.hassette = mock_hassette
    svc._ws_clients = set()
    svc._lock = asyncio.Lock()
    svc._ws_drops = 0
    svc._ws_drops_since_last_log = 0
    svc._ws_drops_last_logged = 0.0
    svc._start_time = 1704067200.0  # 2024-01-01 00:00:00
    svc._subscriptions = []
    svc.logger = MagicMock()
    svc._pending_completions = []
    svc._flush_scheduled = False
    svc.task_bucket = MagicMock()
    svc.task_bucket.spawn = MagicMock(side_effect=lambda coro, **_kw: coro.close())
    return svc


class TestDependencyDecoupling:
    """Dashboard/API services must not transitively wait on app bootstrap."""

    def test_depends_on_excludes_app_handler(self) -> None:
        """RuntimeQueryService no longer declares AppHandler as a startup dependency."""
        assert AppHandler not in RuntimeQueryService.depends_on


class TestPreBootstrapAppState:
    """Registry metadata is queryable and app counts are zero before AppHandler bootstraps apps.

    AppHandler and its AppRegistry are constructed before the Resource lifecycle starts (see
    ``Hassette.wire_services()``), so these reads must be safe even though AppHandler has not
    finished (or even started) app bootstrap.
    """

    def test_get_app_status_snapshot_is_empty_before_bootstrap(self, runtime: RuntimeQueryService) -> None:
        runtime.hassette.app_handler.get_status_snapshot = Mock(return_value=AppStatusSnapshot(instances=[]))

        snapshot = runtime.get_app_status_snapshot()

        assert snapshot.total_count == 0

    def test_get_system_status_reports_zero_apps_before_bootstrap(self, runtime: RuntimeQueryService) -> None:
        runtime.hassette.app_handler.get_status_snapshot = Mock(return_value=AppStatusSnapshot(instances=[]))

        status = runtime.get_system_status()

        assert status.app_count == 0

    def test_overlay_manifest_rows_reflects_configured_registry_before_bootstrap(
        self, runtime: RuntimeQueryService, tmp_path: Path
    ) -> None:
        """A configured-but-not-yet-started app overlays as 'stopped' with in_current_config True."""
        registry = AppRegistry()
        manifest = create_app_manifest("pending", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})
        runtime.hassette.app_handler.registry = registry

        db_row = make_manifest_db_row(app_key=manifest.app_key, class_name=manifest.class_name)
        [info] = runtime.overlay_manifest_rows([db_row])

        assert info.status == "stopped"
        assert info.in_current_config is True

    def test_get_registry_only_apps_reflects_configured_filter_before_bootstrap(
        self, runtime: RuntimeQueryService
    ) -> None:
        registry = AppRegistry()
        registry.set_only_apps(["app_b", "app_a"])
        runtime.hassette.app_handler.registry = registry

        assert runtime.get_registry_only_apps() == ["app_a", "app_b"]

    def test_collect_boot_issues_reports_none_before_any_manifests(self, runtime: RuntimeQueryService) -> None:
        registry = AppRegistry()
        runtime.hassette.app_handler.registry = registry

        assert runtime.collect_boot_issues() == []

    def test_collect_boot_issues_reports_registry_blocked_entries_before_bootstrap(
        self, runtime: RuntimeQueryService, tmp_path: Path
    ) -> None:
        """A registry-level block (e.g. the --app filter) is visible before any instance starts."""
        registry = AppRegistry()
        manifest = create_app_manifest("blocked", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})
        registry.block_app(manifest.app_key, BlockReason.ONLY_APP)
        runtime.hassette.app_handler.registry = registry

        issues = runtime.collect_boot_issues()

        assert len(issues) == 1
        assert issues[0].severity == "warn"

    def test_collect_boot_issues_warns_when_bootstrap_unreleased_with_autostart_app(
        self, runtime: RuntimeQueryService, tmp_path: Path
    ) -> None:
        """An autostart app configured while bootstrap is unreleased produces a warn-level issue."""
        registry = AppRegistry()
        manifest = create_app_manifest("pending_ha", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})
        runtime.hassette.app_handler.registry = registry
        runtime.hassette.app_bootstrap_coordinator.is_released = Mock(return_value=False)

        issues = runtime.collect_boot_issues()

        [pending] = [issue for issue in issues if issue.label == "Apps pending on Home Assistant"]
        assert pending.severity == "warn"

    def test_collect_boot_issues_omits_pending_warning_once_bootstrap_released(
        self, runtime: RuntimeQueryService, tmp_path: Path
    ) -> None:
        registry = AppRegistry()
        manifest = create_app_manifest("released", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})
        runtime.hassette.app_handler.registry = registry
        runtime.hassette.app_bootstrap_coordinator.is_released = Mock(return_value=True)

        issues = runtime.collect_boot_issues()

        assert not any(issue.label == "Apps pending on Home Assistant" for issue in issues)

    def test_collect_boot_issues_reports_degraded_apps_with_error_message(
        self, runtime: RuntimeQueryService, tmp_path: Path
    ) -> None:
        """A DEGRADED manifest (one running instance, one failed instance) surfaces as an
        err-level boot issue, same as a fully-failed app.
        """
        registry = AppRegistry()
        manifest = create_app_manifest("half_broken", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})

        running_app = MagicMock()
        running_app.app_config.instance_name = f"{manifest.class_name}.0"
        running_app.class_name = manifest.class_name
        running_app.status = ResourceStatus.RUNNING
        running_app.unique_name = f"{manifest.class_name}.{manifest.app_key}.0"
        registry.register_app(manifest.app_key, 0, running_app)
        registry.record_failure(manifest.app_key, 1, RuntimeError("instance 1 blew up"))

        runtime.hassette.app_handler.registry = registry

        issues = runtime.collect_boot_issues()

        [failed_issue] = [issue for issue in issues if issue.label == f"App failed: {manifest.display_name}"]
        assert failed_issue.severity == "err"
        assert failed_issue.detail == "instance 1 blew up"


class TestConcurrentAppHandlerTeardown:
    """Reads stay safe under concurrent AppHandler teardown.

    Removing AppHandler from ``depends_on`` also removes the guaranteed reverse shutdown
    ordering a dependency edge would otherwise provide, so RuntimeQueryService can no longer
    assume AppHandler has finished tearing down before its own shutdown runs.
    """

    def test_read_methods_tolerate_registry_cleared_mid_teardown(
        self, runtime: RuntimeQueryService, tmp_path: Path
    ) -> None:
        """Simulates AppHandler.shutdown_all() clearing running apps while reads are in flight."""
        registry = AppRegistry()
        manifest = create_app_manifest("teardown", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})

        app = MagicMock()
        app.app_config.instance_name = "TeardownApp[0]"
        app.class_name = "TeardownApp"
        app.status = ResourceStatus.RUNNING
        app.unique_name = "TeardownApp[0]"
        registry.register_app(manifest.app_key, 0, app)

        runtime.hassette.app_handler.registry = registry
        runtime.hassette.app_handler.get_status_snapshot = Mock(side_effect=registry.get_snapshot)

        # Sanity: the app is visible before teardown starts.
        assert runtime.get_app_status_snapshot().total_count == 1

        # AppHandler.on_shutdown() -> AppLifecycleService.shutdown_all() clears the registry.
        # Without the depends_on edge this can now race RuntimeQueryService's own shutdown.
        registry.clear_all()

        # No read path may raise once AppHandler starts tearing down.
        assert runtime.get_app_status_snapshot().total_count == 0
        assert runtime.get_system_status().app_count == 0
        assert runtime.collect_boot_issues() == []
        assert runtime.get_registry_only_apps() == []
        [info] = runtime.overlay_manifest_rows([make_manifest_db_row(app_key=manifest.app_key)])
        assert info.status == "stopped"

    async def test_on_app_state_changed_is_idempotent_when_registry_entry_is_gone(
        self, runtime: RuntimeQueryService
    ) -> None:
        """Broadcasting an app-state event reads only the event payload, never the registry."""
        broadcast_calls: list[dict] = []
        runtime.broadcast = AsyncMock(side_effect=lambda msg: broadcast_calls.append(msg))
        runtime.hassette.app_handler.registry = AppRegistry()  # already cleared by teardown

        event = MagicMock()
        event.payload.data.app_key = "gone_app"
        event.payload.data.index = 0
        event.payload.data.status = ResourceStatus.STOPPED
        event.payload.data.previous_status = ResourceStatus.RUNNING
        event.payload.data.instance_name = "GoneApp[0]"
        event.payload.data.class_name = "GoneApp"
        event.payload.data.exception = None
        event.payload.data.exception_type = None
        event.payload.data.exception_traceback = None

        await runtime.on_app_state_changed(event)

        assert len(broadcast_calls) == 1
        assert broadcast_calls[0]["data"]["app_key"] == "gone_app"


class TestUnwiredBootstrapCoordinator:
    """The class docstring promises every cross-resource read tolerates teardown/unwired state.

    ``app_bootstrap_coordinator`` is a lazily-wired ``Hassette`` property that raises
    ``RuntimeError`` when the slot hasn't been set yet (see ``core.py``'s
    ``_service_not_wired_error``) — mirroring how ``websocket_service``/``app_handler`` raise.
    Simulated here via ``PropertyMock`` on the mock's per-instance class (the documented way to
    mock a property with ``unittest.mock``), since attribute *access* itself must raise, not a
    method call on the accessed object.
    """

    def test_get_system_status_tolerates_unwired_bootstrap_coordinator(self, runtime: RuntimeQueryService) -> None:
        type(runtime.hassette).app_bootstrap_coordinator = PropertyMock(side_effect=RuntimeError("not wired"))

        status = runtime.get_system_status()

        assert status.bootstrap_released is False

    def test_collect_boot_issues_tolerates_unwired_bootstrap_coordinator(
        self, runtime: RuntimeQueryService, tmp_path: Path
    ) -> None:
        registry = AppRegistry()
        manifest = create_app_manifest("unwired", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})
        runtime.hassette.app_handler.registry = registry
        type(runtime.hassette).app_bootstrap_coordinator = PropertyMock(side_effect=RuntimeError("not wired"))

        issues = runtime.collect_boot_issues()

        assert any(issue.label == "Apps pending on Home Assistant" for issue in issues)


class TestAppStatus:
    def test_get_app_status_snapshot(self, runtime: RuntimeQueryService) -> None:
        snapshot = runtime.get_app_status_snapshot()
        assert isinstance(snapshot, AppStatusSnapshot)
        assert snapshot.total_count == 1
        assert snapshot.running_count == 1
        assert snapshot.failed_count == 0
        assert len(snapshot.instances) == 1
        assert snapshot.instances[0].app_key == "my_app"


class TestCompletionPayloadEnrichment:
    """app_key, instance_index, and kind are read directly from event payload."""

    async def test_handler_payload_carries_app_identity(self, runtime: RuntimeQueryService) -> None:
        """app_key and instance_index from a handler execution are stored in the pending dict."""
        runtime.broadcast = AsyncMock()
        event = HassetteExecutionCompletedEvent.from_record(
            kind="handler", listener_id=42, status="success", duration_ms=5.0, app_key="lights", instance_index=1
        )
        await runtime.on_execution_completed(event)
        assert runtime._pending_completions[0]["app_key"] == "lights"
        assert runtime._pending_completions[0]["instance_index"] == 1
        assert runtime._pending_completions[0]["kind"] == "handler"
        assert runtime._pending_completions[0]["listener_id"] == 42

    async def test_job_payload_carries_app_identity(self, runtime: RuntimeQueryService) -> None:
        """app_key and instance_index from a job execution are stored in the pending dict."""
        runtime.broadcast = AsyncMock()
        event = HassetteExecutionCompletedEvent.from_record(
            kind="job", job_id=99, status="success", duration_ms=8.0, app_key="climate", instance_index=2
        )
        await runtime.on_execution_completed(event)
        assert runtime._pending_completions[0]["app_key"] == "climate"
        assert runtime._pending_completions[0]["instance_index"] == 2
        assert runtime._pending_completions[0]["kind"] == "job"
        assert runtime._pending_completions[0]["job_id"] == 99

    async def test_payload_defaults_to_empty_app_key(self, runtime: RuntimeQueryService) -> None:
        """Events without app_key default to empty string and zero index."""
        runtime.broadcast = AsyncMock()
        event = HassetteExecutionCompletedEvent.from_record(
            kind="handler", listener_id=999, status="success", duration_ms=5.0
        )
        await runtime.on_execution_completed(event)
        assert runtime._pending_completions[0]["app_key"] == ""
        assert runtime._pending_completions[0]["instance_index"] == 0


class TestCompletionBatching:
    """Per-drain batching: all completions in one tick become one unified execution_completed message."""

    async def test_handler_completions_batched_into_one_message(self, runtime: RuntimeQueryService) -> None:
        """Multiple handler execution events in the same tick emit one broadcast."""
        broadcast_calls: list[dict] = []

        async def fake_broadcast(msg: dict) -> None:
            broadcast_calls.append(msg)

        runtime.broadcast = fake_broadcast

        event1 = HassetteExecutionCompletedEvent.from_record(
            kind="handler", listener_id=1, status="success", duration_ms=10.0, app_key="my_app", instance_index=0
        )
        event2 = HassetteExecutionCompletedEvent.from_record(
            kind="handler",
            listener_id=2,
            status="failed",
            duration_ms=20.0,
            app_key="my_app",
            instance_index=0,
            error_type="ValueError",
        )

        await runtime.on_execution_completed(event1)
        await runtime.on_execution_completed(event2)

        # Flush should not have fired yet (still in the same tick)
        assert len(broadcast_calls) == 0

        # Manually flush (simulates asyncio.sleep(0) yielding)
        msg = await assert_flushed_single_message(runtime, broadcast_calls)
        assert msg["data"][0]["kind"] == "handler"
        assert msg["data"][0]["listener_id"] == 1
        assert msg["data"][0]["app_key"] == "my_app"
        assert msg["data"][1]["listener_id"] == 2
        assert msg["data"][1]["status"] == "failed"
        assert msg["data"][1]["error_type"] == "ValueError"

    async def test_job_completions_batched_into_one_message(self, runtime: RuntimeQueryService) -> None:
        """Multiple job execution events in the same tick emit one broadcast."""
        broadcast_calls: list[dict] = []

        async def fake_broadcast(msg: dict) -> None:
            broadcast_calls.append(msg)

        runtime.broadcast = fake_broadcast

        event1 = HassetteExecutionCompletedEvent.from_record(
            kind="job", job_id=10, status="success", duration_ms=50.0, app_key="scheduler_app", instance_index=0
        )
        event2 = HassetteExecutionCompletedEvent.from_record(
            kind="job", job_id=11, status="success", duration_ms=30.0, app_key="scheduler_app", instance_index=0
        )

        await runtime.on_execution_completed(event1)
        await runtime.on_execution_completed(event2)

        assert len(broadcast_calls) == 0
        msg = await assert_flushed_single_message(runtime, broadcast_calls)
        assert msg["data"][0]["kind"] == "job"
        assert msg["data"][1]["kind"] == "job"

    async def test_flush_resets_pending_list(self, runtime: RuntimeQueryService) -> None:
        """After flush, _pending_completions is empty."""
        runtime.broadcast = AsyncMock()

        event = HassetteExecutionCompletedEvent.from_record(
            kind="handler", listener_id=3, status="success", duration_ms=1.0, app_key="app", instance_index=0
        )
        await runtime.on_execution_completed(event)
        assert len(runtime._pending_completions) == 1

        await runtime.flush_completions()
        assert len(runtime._pending_completions) == 0

    async def test_flush_noop_when_no_pending(self, runtime: RuntimeQueryService) -> None:
        """Flush with empty pending list does not call broadcast."""
        runtime.broadcast = AsyncMock()
        await runtime.flush_completions()
        runtime.broadcast.assert_not_awaited()

    async def test_mixed_handler_and_job_emit_single_message(self, runtime: RuntimeQueryService) -> None:
        """Handler and job completions in same tick emit one unified message, not two."""
        broadcast_calls: list[dict] = []

        async def fake_broadcast(msg: dict) -> None:
            broadcast_calls.append(msg)

        runtime.broadcast = fake_broadcast

        handler_event = HassetteExecutionCompletedEvent.from_record(
            kind="handler", listener_id=1, status="success", duration_ms=5.0, app_key="my_app", instance_index=0
        )
        job_event = HassetteExecutionCompletedEvent.from_record(
            kind="job", job_id=10, status="success", duration_ms=8.0, app_key="my_app", instance_index=0
        )

        await runtime.on_execution_completed(handler_event)
        await runtime.on_execution_completed(job_event)

        # Single message containing both handler and job entries
        msg = await assert_flushed_single_message(runtime, broadcast_calls)
        kinds = {item["kind"] for item in msg["data"]}
        assert kinds == {"handler", "job"}


class TestSystemStatus:
    def test_get_system_status(self, runtime: RuntimeQueryService) -> None:
        status = runtime.get_system_status()
        assert isinstance(status, SystemStatus)
        assert status.entity_count == 2
        assert status.app_count == 1
        assert status.log_queue_drops == 0
        assert status.db_write_queue_drops == 0

    def test_get_system_status_reports_log_drop_counters_independently(self, runtime: RuntimeQueryService) -> None:
        runtime.hassette.get_log_queue_drops.return_value = 3
        runtime.hassette.get_db_write_queue_drops.return_value = 7

        status = runtime.get_system_status()

        assert status.log_queue_drops == 3
        assert status.db_write_queue_drops == 7

    def test_system_status_ws_connected_reflects_readiness(self, runtime: RuntimeQueryService) -> None:
        """ws_connected is False when websocket_service.is_connected returns False.

        This covers the early-drop retry case: status is RUNNING but the connection
        is not currently established (the WebSocket dropped post-auth and a retry is
        in progress).
        """
        runtime.hassette.websocket_service.is_connected = False
        status = runtime.get_system_status()
        assert status.websocket_connected is False

    def test_system_status_ws_connected_true_when_ready(self, runtime: RuntimeQueryService) -> None:
        """ws_connected is True when websocket_service.is_connected is True."""
        runtime.hassette.websocket_service.is_connected = True
        status = runtime.get_system_status()
        assert status.websocket_connected is True

    def test_system_status_degraded_when_has_ever_connected_and_not_ready(self, runtime: RuntimeQueryService) -> None:
        """Status is 'degraded' when latch is set and WS is not currently connected."""
        runtime.hassette.websocket_service.is_connected = False
        runtime.hassette.websocket_service.has_ever_connected = True
        status = runtime.get_system_status()
        assert status.status == "degraded"

    def test_system_status_starting_when_never_connected(self, runtime: RuntimeQueryService) -> None:
        """Status is 'starting' when the latch has never been set."""
        runtime.hassette.websocket_service.is_connected = False
        runtime.hassette.websocket_service.has_ever_connected = False
        status = runtime.get_system_status()
        assert status.status == "starting"

    def test_system_status_ok_when_ws_ready(self, runtime: RuntimeQueryService) -> None:
        """Status is 'ok' when websocket_service.is_connected is True."""
        runtime.hassette.websocket_service.is_connected = True
        runtime.hassette.websocket_service.has_ever_connected = True
        status = runtime.get_system_status()
        assert status.status == "ok"
        assert status.bootstrap_released is True

    def test_system_status_degraded_when_connected_but_bootstrap_not_released(
        self, runtime: RuntimeQueryService
    ) -> None:
        """Status is 'degraded' (not 'ok') when WS is connected but app bootstrap hasn't released.

        Covers a permanently-failing state sync with a healthy WebSocket connection: without this
        check, get_system_status() would report "ok" forever while every app stays unbootstrapped.
        """
        runtime.hassette.websocket_service.is_connected = True
        runtime.hassette.websocket_service.has_ever_connected = True
        runtime.hassette.app_bootstrap_coordinator.is_released = Mock(return_value=False)

        status = runtime.get_system_status()

        assert status.status == "degraded"
        assert status.bootstrap_released is False

    def test_system_status_reports_log_persistence_active(self, runtime: RuntimeQueryService) -> None:
        """log_persistence_active is carried through from the Hassette instance."""
        assert runtime.get_system_status().log_persistence_active is True

        runtime.hassette.is_log_persistence_active = Mock(return_value=False)
        assert runtime.get_system_status().log_persistence_active is False


class TestWebSocketClientManagement:
    async def test_register_and_unregister(self, runtime: RuntimeQueryService) -> None:
        queue = await runtime.register_ws_client()
        assert isinstance(queue, asyncio.Queue)
        assert len(runtime._ws_clients) == 1

        await runtime.unregister_ws_client(queue)
        assert len(runtime._ws_clients) == 0

    async def test_broadcast(self, runtime: RuntimeQueryService) -> None:
        queue = await runtime.register_ws_client()
        message = {"type": "test", "data": {"value": 42}}

        await runtime.broadcast(message)

        received = queue.get_nowait()
        assert received == message

        await runtime.unregister_ws_client(queue)

    async def test_broadcast_drops_for_full_queue(self, runtime: RuntimeQueryService) -> None:
        queue = await runtime.register_ws_client()
        # Fill the queue
        for i in range(WS_QUEUE_MAX):
            await queue.put({"type": "filler", "index": i})

        # This should not raise, just drop
        await runtime.broadcast({"type": "dropped"})

        assert queue.qsize() == WS_QUEUE_MAX  # still full, message was dropped

        await runtime.unregister_ws_client(queue)


class TestServiceStatusMapping:
    async def test_on_service_status_maps_ready_fields(self, runtime: RuntimeQueryService) -> None:
        broadcast_calls: list[dict] = []
        runtime.broadcast = AsyncMock(side_effect=lambda msg: broadcast_calls.append(msg))

        event = HassetteServiceEvent.from_service_status(
            resource_name="WebsocketService",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
            ready=True,
            ready_phase="Connected and authenticated",
        )
        await runtime.on_service_status(event)

        assert len(broadcast_calls) == 1
        data = broadcast_calls[0]["data"]
        assert data["ready"] is True
        assert data["ready_phase"] == "Connected and authenticated"

    async def test_on_service_status_defaults_ready_false(self, runtime: RuntimeQueryService) -> None:
        # dup-ignore-start: structurally mirrors service_watcher_coverage.py's make_running_event
        # helper (both build a HassetteServiceEvent via from_service_status), but this test
        # exercises RuntimeQueryService's web-layer broadcast mapping, a different component and
        # test tier from ServiceWatcher's log_service_event — see design.md's cross-scope
        # treatment rationale for tests/unit/core/ clusters that reach outside the scoped group.
        broadcast_calls: list[dict] = []
        runtime.broadcast = AsyncMock(side_effect=lambda msg: broadcast_calls.append(msg))

        event = HassetteServiceEvent.from_service_status(
            resource_name="SomeService",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.STARTING,
        )
        # dup-ignore-end
        await runtime.on_service_status(event)

        assert len(broadcast_calls) == 1
        data = broadcast_calls[0]["data"]
        assert data["ready"] is False
        assert data["ready_phase"] is None
