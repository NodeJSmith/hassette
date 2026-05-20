"""Unit tests for AppLifecycleService — app operations and reconciliation."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.types import Topic
from hassette.types.enums import BlockReason, ResourceStatus


@pytest.fixture
def mock_hassette() -> AsyncMock:
    """Create a mock Hassette instance with config."""
    hassette = make_mock_hassette(
        sealed=False,
        dev_mode=True,
        logging={"app_handler": "DEBUG"},
        lifecycle={"app_startup_timeout_seconds": 30},
    )
    hassette.send_event = AsyncMock()
    hassette.command_executor = MagicMock()
    hassette.command_executor.reconcile_registrations = AsyncMock()
    hassette.bus_service = MagicMock()
    hassette.bus_service.await_registrations_complete = AsyncMock()
    hassette.bus_service.router = MagicMock()
    hassette.bus_service.router.get_listeners_by_owner = Mock(return_value=[])
    hassette.scheduler_service = MagicMock()
    hassette.scheduler_service.await_registrations_complete = AsyncMock()
    hassette.session_id = 1
    return hassette


@pytest.fixture
def mock_registry() -> MagicMock:
    """Create a mock AppRegistry instance."""
    registry = MagicMock()
    registry.record_failure = Mock()
    registry.all_apps = Mock(return_value=[])
    registry.clear_all = Mock()
    registry.get_manifest = Mock(return_value=None)
    registry.get_apps_by_key = Mock(return_value={})
    registry.register_app = Mock()
    registry.unregister_app = Mock(return_value=None)
    registry.set_manifests = Mock()
    registry.set_only_app = Mock()
    registry.apps = {}
    registry.manifests = {}
    registry.enabled_manifests = {}
    registry.active_manifests = {}
    registry.only_app = None
    registry.get_snapshot = Mock()
    registry.block_app = Mock()
    registry.unblock_apps = Mock(return_value=set())
    return registry


@pytest.fixture
def mock_factory() -> MagicMock:
    """Create a mock AppFactory."""
    factory = MagicMock()
    factory.create_instances = Mock()
    factory.check_only_app_decorator = Mock(return_value=False)
    return factory


@pytest.fixture
def mock_manifest() -> MagicMock:
    """Create a mock AppManifest instance."""
    manifest = MagicMock()
    manifest.class_name = "TestApp"
    manifest.app_key = "test_app"
    manifest.full_path = Path("/apps/test_app.py")
    manifest.display_name = "Test App"
    manifest.enabled = True
    return manifest


@pytest.fixture
def mock_app_instance() -> AsyncMock:
    """Create a mock App instance."""
    app = AsyncMock()
    app.app_config = MagicMock()
    app.app_config.instance_name = "test_instance"
    app.status = ResourceStatus.NOT_STARTED
    app.class_name = "MockApp"
    app.initialize = AsyncMock()
    app.shutdown = AsyncMock()
    app.mark_ready = Mock()
    app.logger = Mock()
    app.bus = MagicMock()
    app.bus.get_listeners = Mock(return_value=[])
    app.bus.owner_id = "MockApp.test_instance"
    app.scheduler = MagicMock()
    app.scheduler.get_job_db_ids = Mock(return_value=[])
    return app


@pytest.fixture
def lifecycle_service(
    mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
) -> AppLifecycleService:
    """Create an AppLifecycleService with mocked dependencies."""
    logging.getLogger("hassette").propagate = True

    with (
        patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
        patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
    ):
        service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
    service.factory = mock_factory
    return service


class TestApplyChanges:
    async def test_routes_changes_to_correct_methods(self, lifecycle_service: AppLifecycleService) -> None:
        """Routes orphans/reimport/reload/new to correct methods."""
        lifecycle_service.stop_app = AsyncMock()
        lifecycle_service.reload_app = AsyncMock()
        lifecycle_service.start_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset({"orphan_app"}),
            new_apps=frozenset({"new_app"}),
            reimport_apps=frozenset({"reimport_app"}),
            reload_apps=frozenset({"reload_app"}),
        )

        await lifecycle_service.apply_changes(changes)

        lifecycle_service.stop_app.assert_called_once_with("orphan_app")
        lifecycle_service.reload_app.assert_any_call("reimport_app", force_reload=True)
        lifecycle_service.reload_app.assert_any_call("reload_app")
        lifecycle_service.start_app.assert_called_once_with("new_app")


class TestStartApp:
    async def test_creates_instances_via_factory(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Calls factory.create_instances with correct app_key."""
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_apps_by_key = Mock(return_value={})

        await lifecycle_service.start_app("test_app")

        mock_factory.create_instances.assert_called_once_with("test_app", mock_manifest, force_reload=False)

    async def test_emits_not_started_event(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
    ) -> None:
        """Emits NOT_STARTED event for each created instance."""
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_apps_by_key = Mock(return_value={0: mock_app_instance})

        await lifecycle_service.start_app("test_app")

        calls = mock_hassette.send_event.call_args_list
        not_started_calls = [
            call
            for call in calls
            if call[0][0] == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
            and call[0][1].payload.data.status == ResourceStatus.NOT_STARTED
        ]
        assert len(not_started_calls) == 1

    async def test_reconcile_registrations_called_after_init(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
    ) -> None:
        """reconcile_registrations() is called after instances are initialized (not before)."""
        initialize_order: list[str] = []

        async def _track_initialize() -> None:
            initialize_order.append("initialize")

        async def _track_reconcile(*_args: object, **_kwargs: object) -> None:
            initialize_order.append("reconcile")

        mock_app_instance.initialize = AsyncMock(side_effect=_track_initialize)
        mock_hassette.command_executor.reconcile_registrations = AsyncMock(side_effect=_track_reconcile)

        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_apps_by_key = Mock(return_value={0: mock_app_instance})

        await lifecycle_service.start_app("test_app")

        assert initialize_order == ["initialize", "reconcile"]

    async def test_skips_disabled_app(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """Skips app when manifest is not found (disabled or unknown)."""
        mock_registry.get_manifest = Mock(return_value=None)

        await lifecycle_service.start_app("disabled_app")

        mock_factory.create_instances.assert_not_called()

    async def test_handles_factory_load_error(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Handles exception from factory.create_instances gracefully."""
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.create_instances.side_effect = RuntimeError("Load failed")

        # Should not raise
        await lifecycle_service.start_app("test_app")

        mock_registry.get_apps_by_key.assert_not_called()


class TestStopApp:
    async def test_unregisters_and_shuts_down(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Unregisters app and shuts down its instances."""
        app1 = AsyncMock()
        app1.status = ResourceStatus.RUNNING
        instances = {0: app1}
        mock_registry.unregister_app = Mock(return_value=instances)

        await lifecycle_service.stop_app("test_app")

        mock_registry.unregister_app.assert_called_once_with("test_app")
        app1.shutdown.assert_called_once()

    async def test_warns_if_not_found(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """Returns early without shutting down any instances when app is not found."""
        mock_registry.unregister_app = Mock(return_value=None)

        await lifecycle_service.stop_app("missing_app")

        mock_registry.unregister_app.assert_called_once_with("missing_app")


class TestReloadApp:
    async def test_stops_then_starts(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Calls stop_app then start_app."""
        mock_registry.unregister_app = Mock(return_value=None)
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_apps_by_key = Mock(return_value={})

        await lifecycle_service.reload_app("test_app")

        mock_registry.unregister_app.assert_called_once_with("test_app")
        mock_factory.create_instances.assert_called_once()


class TestReconcileBlockedApps:
    def test_blocks_non_only_apps(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Blocks all apps except the only_app."""
        mock_registry.only_app = "app_a"
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock(), "app_c": MagicMock()}
        mock_registry.unblock_apps = Mock(return_value=set())

        lifecycle_service.reconcile_blocked_apps()

        block_calls = mock_registry.block_app.call_args_list
        blocked_keys = {call[0][0] for call in block_calls}
        assert blocked_keys == {"app_b", "app_c"}
        for call in block_calls:
            assert call[0][1] == BlockReason.ONLY_APP

    def test_unblocks_when_only_app_cleared(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Unblocks previously blocked apps when only_app is None."""
        mock_registry.only_app = None
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock()}
        mock_registry.unblock_apps = Mock(return_value={"app_b"})

        result = lifecycle_service.reconcile_blocked_apps()

        mock_registry.unblock_apps.assert_called_once_with(BlockReason.ONLY_APP)
        mock_registry.block_app.assert_not_called()
        assert result == {"app_b"}


class TestResolveOnlyApp:
    async def test_sets_only_app_when_decorated(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """Sets only_app filter when a decorated app is found."""
        mock_registry.active_manifests = {"test_app": mock_manifest}
        mock_factory.check_only_app_decorator = Mock(return_value=True)

        await lifecycle_service.resolve_only_app()

        mock_registry.set_only_app.assert_called_with("test_app")

    async def test_clears_only_app_when_none_decorated(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """Clears only_app filter when no decorated app is found."""
        mock_registry.active_manifests = {"test_app": mock_manifest}
        mock_factory.check_only_app_decorator = Mock(return_value=False)

        await lifecycle_service.resolve_only_app()

        mock_registry.set_only_app.assert_called_with(None)

    async def test_disallows_only_app_in_prod_by_default(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """Disallows only_app in production mode when not explicitly allowed."""
        mock_hassette.config.dev_mode = False
        mock_hassette.config.allow_only_app_in_prod = False
        mock_registry.active_manifests = {"test_app": mock_manifest}
        mock_factory.check_only_app_decorator = Mock(return_value=True)

        await lifecycle_service.resolve_only_app()

        mock_registry.set_only_app.assert_called_with(None)


class TestRefreshConfig:
    async def test_reloads_config_and_returns_before_after(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """Calls config.reload() and returns original and current manifests."""
        manifest1 = MagicMock()
        manifest1.enabled = True
        mock_registry.manifests = {"app_a": manifest1}
        mock_hassette.config.app.manifests = {"app_a": manifest1}
        reload_mock = Mock()
        object.__setattr__(mock_hassette.config, "reload", reload_mock)

        original, current = await lifecycle_service.refresh_config()

        reload_mock.assert_called_once()
        assert "app_a" in original
        assert "app_a" in current


class TestReconcileAppRegistrations:
    """Tests for _reconcile_app_registrations — the post-ready reconciliation helper."""

    async def test_scheduler_barrier_awaited_before_job_ids_collected(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_app_instance: AsyncMock,
    ) -> None:
        """Scheduler await barrier is called before live_job_ids are collected.

        Finding 1 (CRITICAL): SchedulerService.await_registrations_complete() must be
        awaited before collecting job db_ids to ensure all pending registration tasks
        have flushed. Without this barrier, jobs whose registration tasks haven't
        completed yet have db_id=None and are absent from live_job_ids — causing
        reconciliation to incorrectly retire their DB rows.
        """
        call_order: list[str] = []

        async def _track_scheduler_barrier(app_key: str) -> None:
            call_order.append(f"scheduler_barrier:{app_key}")

        def _track_get_job_ids() -> list[int]:
            call_order.append("get_job_db_ids")
            return []

        mock_hassette.scheduler_service.await_registrations_complete = AsyncMock(side_effect=_track_scheduler_barrier)
        mock_app_instance.scheduler.get_job_db_ids = Mock(side_effect=_track_get_job_ids)

        instances = {0: mock_app_instance}
        await lifecycle_service._reconcile_app_registrations("test_app", instances)

        # scheduler barrier must appear before get_job_db_ids
        assert "scheduler_barrier:test_app" in call_order, "Scheduler barrier was not called"
        assert "get_job_db_ids" in call_order, "get_job_db_ids was not called"
        scheduler_idx = call_order.index("scheduler_barrier:test_app")
        job_ids_idx = call_order.index("get_job_db_ids")
        assert scheduler_idx < job_ids_idx, (
            f"Scheduler barrier ({scheduler_idx}) must come before get_job_db_ids ({job_ids_idx})"
        )

    async def test_bus_barrier_awaited_before_scheduler_barrier(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_app_instance: AsyncMock,
    ) -> None:
        """Bus await barrier is called before scheduler barrier."""
        call_order: list[str] = []

        async def _track_bus_barrier(_app_key: str) -> None:
            call_order.append("bus_barrier")

        async def _track_scheduler_barrier(_app_key: str) -> None:
            call_order.append("scheduler_barrier")

        mock_hassette.bus_service.await_registrations_complete = AsyncMock(side_effect=_track_bus_barrier)
        mock_hassette.scheduler_service.await_registrations_complete = AsyncMock(side_effect=_track_scheduler_barrier)

        instances = {0: mock_app_instance}
        await lifecycle_service._reconcile_app_registrations("test_app", instances)

        assert call_order.index("bus_barrier") < call_order.index("scheduler_barrier")

    async def test_reconcile_calls_reconcile_registrations(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_app_instance: AsyncMock,
    ) -> None:
        """reconcile_registrations() is called with live IDs after barriers complete."""
        instances = {0: mock_app_instance}
        await lifecycle_service._reconcile_app_registrations("test_app", instances)

        mock_hassette.command_executor.reconcile_registrations.assert_awaited_once()
        call_kwargs = mock_hassette.command_executor.reconcile_registrations.call_args
        assert call_kwargs.args[0] == "test_app"

    async def test_reconcile_failure_does_not_raise(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_app_instance: AsyncMock,
    ) -> None:
        """Reconciliation failure is swallowed — does not propagate to caller."""
        mock_hassette.command_executor.reconcile_registrations = AsyncMock(side_effect=RuntimeError("DB full"))

        instances = {0: mock_app_instance}

        await lifecycle_service._reconcile_app_registrations("test_app", instances)


class TestSetAppsConfigs:
    def test_sets_manifests_on_registry(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls registry.set_manifests with the provided config."""
        manifests = {"app_a": MagicMock()}

        lifecycle_service.set_apps_configs(manifests)

        mock_registry.set_manifests.assert_called_once()
        mock_registry.set_only_app.assert_called_with(None)
