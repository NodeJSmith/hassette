"""Unit tests for AppLifecycleService — whole-app start and stop operations.

Part of the AppLifecycleService unit-test family (``test_app_lifecycle_service*.py``);
shared fixtures live in ``_fixtures_app_lifecycle.py`` via ``conftest.py``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
import structlog
from hassette_wire import ResourceStatus

from hassette.core.app_lifecycle_common import AppAdmissionMode
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry
from hassette.exceptions import AppBlockedError, AppBootstrapNotReleasedError
from hassette.resources.teardown import TeardownReport
from hassette.testing import EventCapture, wait_for
from tests.support.web_manifest_helpers import make_app_instance_info
from tests.unit.core._fixtures_app_lifecycle import make_mock_app_instance

from .conftest import app_state_payloads


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

        not_started_calls = app_state_payloads(event_capture, ResourceStatus.NOT_STARTED)
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

        Raises AppBlockedError rather than silently no-op'ing (P2 follow-up finding on the
        same PR) — a plain no-op would let the web route respond 202 "accepted" for a request
        nothing acted on.
        """
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.is_blocked = Mock(return_value=True)

        with pytest.raises(AppBlockedError):
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
        pruned_info = make_app_instance_info(
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

        stopped_payloads = app_state_payloads(event_capture, ResourceStatus.STOPPED)
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
        failure_info = make_app_instance_info(
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

        failed_payloads = app_state_payloads(event_capture, ResourceStatus.FAILED)
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

    # dup-ignore-start: pytest test function signature
    async def test_does_not_reinitialize_pre_existing_instances(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """Calling start_app() when some indices are already running must not re-initialize
        the pre-existing instances — only newly created ones get on_initialize(). Without this
        guard, the preserved instance would have listeners, jobs, and tasks duplicated (#1688).
        """
        mock_registry.get_manifest = Mock(return_value=mock_manifest)

        existing_app = make_mock_app_instance(instance_name="existing")
        new_app = make_mock_app_instance(instance_name="new")

        # Factory reports only index 2 was created; index 0 was pre-existing.
        mock_factory.create_instances = Mock(return_value={2})

        # Registry returns both: index 0 (pre-existing) and index 2 (newly created).
        mock_registry.get_running_apps = Mock(return_value={0: existing_app, 2: new_app})

        await lifecycle_service.start_app("test_app")

        # Only the newly created instance should be initialized.
        new_app.initialize.assert_awaited_once()
        existing_app.initialize.assert_not_awaited()
        # dup-ignore-end


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


def register_mock_instance(registry: AppRegistry, app_key: str, index: int) -> AsyncMock:
    """Register a mock app instance at ``(app_key, index)`` in a real registry and return it."""
    inst = make_mock_app_instance(instance_name=f"{app_key}.{index}")
    inst.app_key = app_key
    inst.status = ResourceStatus.RUNNING
    registry.register_app(app_key, index, inst)
    return inst


class TestStopApp:
    async def test_shuts_down_and_unregisters(self, real_registry_service: AppLifecycleService) -> None:
        """Shuts down the app's instances and leaves nothing registered."""
        registry = real_registry_service.registry
        inst = register_mock_instance(registry, "test_app", 0)

        await real_registry_service.stop_app("test_app")

        inst.shutdown.assert_awaited_once()
        assert registry.tracked_indices("test_app") == set()

    async def test_instance_stays_registered_until_its_teardown_finishes(
        self, real_registry_service: AppLifecycleService
    ) -> None:
        """While ``on_shutdown`` runs, readers see the instance itself, not a STOPPED placeholder."""
        registry = real_registry_service.registry
        inst = register_mock_instance(registry, "test_app", 0)
        seen_during_teardown: list[object] = []

        async def teardown() -> TeardownReport:
            seen_during_teardown.append(registry.get("test_app", 0))
            return TeardownReport()

        inst.shutdown = AsyncMock(side_effect=teardown)

        await real_registry_service.stop_app("test_app")

        assert seen_during_teardown == [inst]
        assert registry.get("test_app", 0) is None

    async def test_warns_if_not_found(self, real_registry_service: AppLifecycleService) -> None:
        """An app key with nothing tracked is "not found" and shuts nothing down."""
        real_registry_service.shutdown_instances = AsyncMock()

        await real_registry_service.stop_app("missing_app")

        real_registry_service.shutdown_instances.assert_not_called()

    async def test_no_shutdown_when_only_failed_entries_existed(
        self, real_registry_service: AppLifecycleService
    ) -> None:
        """A failed-only app is not "not found": its entries are discarded and nothing is shut down."""
        registry = real_registry_service.registry
        registry.record_failure("failed_only_app", 0, ValueError("bad config"))
        real_registry_service.shutdown_instances = AsyncMock()

        await real_registry_service.stop_app("failed_only_app")

        real_registry_service.shutdown_instances.assert_not_called()
        assert registry.tracked_indices("failed_only_app") == set()

    # dup-ignore-start: pytest test function signature — Python has no way to share a function
    # signature between separate test functions (see .claude/rules/tests-unit-core.md).
    async def test_emits_stopped_event_for_discarded_failed_entries(
        self,
        real_registry_service: AppLifecycleService,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """A discarded failed entry gets a STOPPED event, so the WS status cache doesn't stay on FAILED
        forever, even for a mixed-status app whose running instances emit their own events.
        """
        event_capture.install(mock_hassette)
        registry = real_registry_service.registry
        register_mock_instance(registry, "mixed_app", 0)
        registry.record_failure("mixed_app", 1, ValueError("bad config"))

        await real_registry_service.stop_app("mixed_app")

        stopped_payloads = [p for p in app_state_payloads(event_capture, ResourceStatus.STOPPED) if p.index == 1]
        assert len(stopped_payloads) == 1
        assert stopped_payloads[0].app_key == "mixed_app"
        assert stopped_payloads[0].previous_status == ResourceStatus.FAILED
        # dup-ignore-end

    async def test_flagged_index_emits_failed_not_stopped_and_stays_flagged(
        self,
        real_registry_service: AppLifecycleService,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """A stop discards a flagged index's failure entry, but it keeps reporting FAILED until restart."""
        event_capture.install(mock_hassette)
        registry = real_registry_service.registry
        registry.record_failure("test_app", 0, TimeoutError("stop timed out"))
        registry.flag_needs_restart(
            "test_app", 0, instance_name="test_app.0", class_name="TestApp", reason="work still running"
        )

        await real_registry_service.stop_app("test_app")

        assert app_state_payloads(event_capture, ResourceStatus.STOPPED) == []
        failed = app_state_payloads(event_capture, ResourceStatus.FAILED)
        assert [p.index for p in failed] == [0]
        info = registry.resolve_instance_info("test_app", 0)
        assert info is not None
        assert info.status == ResourceStatus.FAILED
        assert info.needs_restart is not None


class TestExitReachesInFlightStops:
    async def test_shutdown_all_reaches_a_runtime_stop_still_in_flight(
        self, real_registry_service: AppLifecycleService
    ) -> None:
        """A runtime stop keeps its instance registered until the teardown ends, so process exit reaches it
        instead of leaving it unrecorded. Joining that attempt (one body run for both callers) is the
        coordinator's job and is pinned by the resource lifecycle tests; the mock here counts calls only.
        """
        registry = real_registry_service.registry
        inst = register_mock_instance(registry, "test_app", 0)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_teardown() -> TeardownReport:
            entered.set()
            await release.wait()
            return TeardownReport()

        inst.shutdown = AsyncMock(side_effect=slow_teardown)
        runtime_stop = asyncio.create_task(real_registry_service.stop_app("test_app"))
        await asyncio.wait_for(entered.wait(), timeout=5)

        exit_stop = asyncio.create_task(real_registry_service.shutdown_all())
        await wait_for(lambda: inst.shutdown.await_count == 2, desc="exit joined the in-flight stop")
        release.set()
        await asyncio.wait_for(asyncio.gather(runtime_stop, exit_stop), timeout=5)

        assert registry.tracked_indices("test_app") == set()


class TestShutdownInstanceLogContext:
    async def test_binds_real_app_key_during_shutdown(self, lifecycle_service: AppLifecycleService) -> None:
        """Log records emitted while an instance shuts down carry its real app_key, not None."""
        inst = make_mock_app_instance(instance_name="inst_0")
        inst.app_key = "my_app"
        bound: dict[str, object] = {}

        async def capture_context() -> TeardownReport:
            bound.update(structlog.contextvars.get_contextvars())
            return TeardownReport()

        inst.shutdown = AsyncMock(side_effect=capture_context)

        await lifecycle_service.shutdown_instance(inst, 0)

        assert bound["app_key"] == "my_app"
        assert bound["instance_name"] == "inst_0"
        assert bound["instance_index"] == 0
        assert "app_key" not in structlog.contextvars.get_contextvars()
