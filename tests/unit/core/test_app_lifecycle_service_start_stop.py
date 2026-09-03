"""Unit tests for AppLifecycleService — whole-app start and stop operations.

Part of the AppLifecycleService unit-test family (``test_app_lifecycle_service*.py``);
shared fixtures live in ``_fixtures_app_lifecycle.py`` via ``conftest.py``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from hassette.core.app_lifecycle_service import AppAdmissionMode, AppLifecycleService
from hassette.exceptions import AppBootstrapNotReleasedError
from hassette.schemas.app_snapshots import AppInstanceInfo
from hassette.test_utils import EventCapture
from hassette.types import Topic
from hassette.types.enums import ResourceStatus


class TestStartApp:
    async def test_wait_mode_awaits_release_before_creating_instances(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})
        mock_hassette.app_bootstrap_coordinator.is_released.return_value = False

        await lifecycle_service.start_app("test_app", admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

        mock_hassette.app_bootstrap_coordinator.wait_released.assert_awaited_once_with()
        mock_factory.create_instances.assert_called_once_with("test_app", mock_manifest, force_reload=False)

    async def test_rejects_when_unreleased_in_manual_mode(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """REJECT_IF_UNRELEASED fails immediately and retains no waiting task."""
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_hassette.app_bootstrap_coordinator.is_released.return_value = False

        with pytest.raises(AppBootstrapNotReleasedError):
            await lifecycle_service.start_app("test_app")

        mock_factory.create_instances.assert_not_called()
        # The manual-mode admission check must never await the release latch — that would
        # retain a waiting task instead of failing immediately.
        mock_hassette.app_bootstrap_coordinator.wait_released.assert_not_awaited()

    async def test_creates_instances_via_factory(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Calls factory.create_instances with correct app_key."""
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})

        await lifecycle_service.start_app("test_app")

        mock_factory.create_instances.assert_called_once_with("test_app", mock_manifest, force_reload=False)

    async def test_emits_not_started_event(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Emits NOT_STARTED event for each created instance."""
        event_capture.install(mock_hassette)
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={0: mock_app_instance})

        await lifecycle_service.start_app("test_app")

        not_started_calls = [
            payload
            for payload in event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED)
            if payload.status == ResourceStatus.NOT_STARTED
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
        mock_registry.get_running_apps = Mock(return_value={0: mock_app_instance})

        await lifecycle_service.start_app("test_app")

        assert initialize_order == ["initialize", "reconcile"]

    async def test_skips_disabled_app(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """Skips app when manifest is not found (disabled or unknown)."""
        mock_registry.get_manifest = Mock(return_value=None)

        await lifecycle_service.start_app("disabled_app")

        mock_factory.create_instances.assert_not_called()

    async def test_skips_blocked_app(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """A manual start_app() for an app excluded by the --app filter must not bypass that
        exclusion — regression test for the P1 finding on PR #1873: the
        manifest for a blocked app still exists and still reports a configured instance count,
        so nothing else in start_app()/_start_app_unlocked() would otherwise stop it.
        """
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.is_blocked = Mock(return_value=True)

        await lifecycle_service.start_app("blocked_app")

        mock_factory.create_instances.assert_not_called()

    async def test_prunes_stale_failed_indices_before_creating_instances(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """A config shrink (e.g. 3 configured instances -> 1) must prune failed entries at the
        now-removed indices before create_instances() runs. Pruning happens here (not inside
        AppFactory.create_instances()) so it applies uniformly even when class-loading itself
        fails, and so pruned entries can be reported to WS subscribers as STOPPED (see the next
        test) instead of discarded silently.
        """
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})
        mock_factory.normalize_configs = Mock(return_value=[{"instance_name": "test_instance"}])

        await lifecycle_service.start_app("test_app")

        mock_registry.prune_stale_failed_indices.assert_called_once_with("test_app", 1)
        mock_factory.normalize_configs.assert_called_once_with(mock_manifest.app_config)

    async def test_prunes_before_creating_instances_not_after(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Pruning must run before create_instances(), not after — create_instances() returns
        early without running its own instance loop when class-loading fails, so pruning could
        never reliably run afterward for that path.
        """
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})
        call_order: list[str] = []

        def _record_prune(*_args: object, **_kwargs: object) -> dict[int, object]:
            call_order.append("prune")
            return {}

        def _record_create_instances(*_args: object, **_kwargs: object) -> None:
            call_order.append("create_instances")

        mock_registry.prune_stale_failed_indices = Mock(side_effect=_record_prune)
        mock_factory.create_instances = Mock(side_effect=_record_create_instances)

        await lifecycle_service.start_app("test_app")

        assert call_order == ["prune", "create_instances"]

    async def test_emits_stopped_event_for_pruned_stale_failed_entries(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Pruned entries must not be discarded silently — without a STOPPED event, the WS
        status cache for that index stays on FAILED forever, and if the config shrinks to a
        single remaining instance, appLiveStatus() falls back to reading exactly that stale
        cache entry (frontend/src/utils/app-data.ts's instances.length <= 1 branch) — the same
        vulnerability shape as the discarded-on-stop bug this mirrors.
        """
        event_capture.install(mock_hassette)
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})
        pruned_info = AppInstanceInfo(
            app_key="test_app",
            index=2,
            instance_name="test_app.2",
            class_name="TestApp",
            status=ResourceStatus.FAILED,
            error=ValueError("stale - index removed from config"),
            error_message="stale - index removed from config",
            error_traceback="Traceback...",
        )
        mock_registry.prune_stale_failed_indices = Mock(return_value={2: pruned_info})

        await lifecycle_service.start_app("test_app")

        stopped_payloads = [
            payload
            for payload in event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED)
            if payload.status == ResourceStatus.STOPPED
        ]
        assert len(stopped_payloads) == 1
        payload = stopped_payloads[0]
        assert payload.app_key == "test_app"
        assert payload.index == 2
        assert payload.previous_status == ResourceStatus.FAILED
        assert payload.exception is None  # STOPPED events don't carry the prior failure's exception info

    async def test_emits_state_event_for_pre_instantiation_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """create_instances() records failures that occur before an App object exists (invalid
        instance_name, config validation, class load error) straight to the registry, with no
        App to build an app_status_changed event from. Without emitting one here, those failures
        never reach WS subscribers, and a stale cached status lingers instead of updating to
        FAILED — see the masked-degraded-status bug this closes.
        """
        event_capture.install(mock_hassette)
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})
        failure_info = AppInstanceInfo(
            app_key="test_app",
            index=0,
            instance_name="test_app.0",
            class_name="TestApp",
            status=ResourceStatus.FAILED,
            error=ValueError("bad config"),
            error_message="bad config",
            error_traceback="Traceback (most recent call last)...",
        )
        mock_registry.get_failed_instance_infos = Mock(return_value={0: failure_info})

        await lifecycle_service.start_app("test_app")

        failed_payloads = [
            payload
            for payload in event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED)
            if payload.status == ResourceStatus.FAILED
        ]
        assert len(failed_payloads) == 1
        payload = failed_payloads[0]
        assert payload.app_key == "test_app"
        assert payload.index == 0
        assert payload.instance_name == "test_app.0"
        assert payload.exception == "bad config"

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

        mock_registry.get_running_apps.assert_not_called()


class TestStartAppStaleManifestRace:
    """Pin: a manifest removed while start_app() is parked in _admit_start() must not be used.

    _admit_start() can block indefinitely (WAIT_FOR_RELEASE awaits AppBootstrapCoordinator's
    release latch). If start_app() captures ``app_manifest`` before that wait and never
    rechecks, a concurrent file-watcher event that removes the manifest while the wait is
    parked leaves start_app() creating instances from a manifest that no longer exists in
    the registry.
    """

    async def test_manifest_removed_during_admission_wait_is_not_used(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        gate = asyncio.Event()
        entered = asyncio.Event()
        manifest_removed = False

        def get_manifest_side_effect(_key: str) -> MagicMock | None:
            return None if manifest_removed else mock_manifest

        mock_registry.get_manifest = Mock(side_effect=get_manifest_side_effect)
        mock_registry.get_running_apps = Mock(return_value={})

        async def blocked_wait_released() -> None:
            entered.set()  # signal the moment the admission wait is entered
            await gate.wait()

        mock_hassette.app_bootstrap_coordinator.wait_released = AsyncMock(side_effect=blocked_wait_released)

        task = asyncio.create_task(
            lifecycle_service.start_app("test_app", admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert not task.done()  # confirms the gate is actually blocking start_app()

        # Simulate a concurrent file-watcher reconciliation removing the app's manifest
        # while start_app() is parked in the admission wait.
        manifest_removed = True

        gate.set()
        await asyncio.wait_for(task, timeout=1)

        # The stale, pre-admission manifest must never reach the factory.
        mock_factory.create_instances.assert_not_called()


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

    async def test_no_shutdown_when_only_failed_entries_existed(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """unregister_app returning {} (entries existed but none were running, e.g. a
        failed-only app) is not treated as "not found" and does not call shutdown_instances.
        """
        mock_registry.unregister_app = Mock(return_value={})
        lifecycle_service.shutdown_instances = AsyncMock()

        await lifecycle_service.stop_app("failed_only_app")

        mock_registry.unregister_app.assert_called_once_with("failed_only_app")
        lifecycle_service.shutdown_instances.assert_not_called()

    async def test_emits_stopped_event_for_discarded_failed_entries(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """unregister_app() discards failed entries silently — it only returns the running
        ones. Without emitting something for them, the WS status cache for those indices never
        learns the app stopped and stays on FAILED/degraded forever, even for a mixed-status app
        where the running instances stopped cleanly and correctly emitted their own events.
        """
        event_capture.install(mock_hassette)
        failed_info = AppInstanceInfo(
            app_key="mixed_app",
            index=1,
            instance_name="mixed_app.1",
            class_name="MixedApp",
            status=ResourceStatus.FAILED,
            error=ValueError("bad config"),
            error_message="bad config",
            error_traceback="Traceback...",
        )
        mock_registry.get_failed_instance_infos = Mock(return_value={1: failed_info})
        mock_registry.unregister_app = Mock(return_value={})

        await lifecycle_service.stop_app("mixed_app")

        stopped_payloads = [
            payload
            for payload in event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED)
            if payload.status == ResourceStatus.STOPPED
        ]
        assert len(stopped_payloads) == 1
        payload = stopped_payloads[0]
        assert payload.app_key == "mixed_app"
        assert payload.index == 1
        assert payload.previous_status == ResourceStatus.FAILED

    async def test_captures_failed_infos_before_unregister_discards_them(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """get_failed_instance_infos() must be called before unregister_app() — the latter is
        what discards the failed entries, so calling get_failed_instance_infos() afterward would
        always see an already-empty registry and silently emit nothing.
        """
        call_order: list[str] = []

        def _record_get_failed_instance_infos(_key: str) -> dict[int, object]:
            call_order.append("get_failed_instance_infos")
            return {}

        def _record_unregister_app(_key: str) -> dict[int, object]:
            call_order.append("unregister_app")
            return {}

        mock_registry.get_failed_instance_infos = Mock(side_effect=_record_get_failed_instance_infos)
        mock_registry.unregister_app = Mock(side_effect=_record_unregister_app)

        await lifecycle_service.stop_app("test_app")

        assert call_order == ["get_failed_instance_infos", "unregister_app"]
