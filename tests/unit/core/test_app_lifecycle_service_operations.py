"""Unit tests for AppLifecycleService — app operations and reconciliation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppAdmissionMode, AppLifecycleService
from hassette.exceptions import AppBootstrapNotReleasedError
from hassette.schemas.app_snapshots import AppInstanceInfo
from hassette.test_utils import EventCapture, wait_for
from hassette.types import Topic
from hassette.types.enums import BlockReason, ResourceStatus


class TestApplyChanges:
    async def test_routes_changes_to_correct_methods(self, lifecycle_service: AppLifecycleService) -> None:
        """Routes orphans/reimport/reload/new to correct methods when autostart gates pass."""
        lifecycle_service.stop_app = AsyncMock()
        lifecycle_service.reload_app = AsyncMock()
        lifecycle_service.start_app = AsyncMock()
        # Gates are transparent for autostart=True apps — mock helpers so this test stays
        # focused on routing, not gating (gating is covered by TestApplyChangesGating).
        lifecycle_service.should_autostart = Mock(return_value=True)
        lifecycle_service.should_auto_reconcile = Mock(return_value=True)

        changes = ChangeSet(
            orphans=frozenset({"orphan_app"}),
            new_apps=frozenset({"new_app"}),
            reimport_apps=frozenset({"reimport_app"}),
            reload_apps=frozenset({"reload_app"}),
        )

        await lifecycle_service.apply_changes(changes, {}, {})

        lifecycle_service.stop_app.assert_called_once_with("orphan_app")
        lifecycle_service.reload_app.assert_any_call("reimport_app", force_reload=True)
        lifecycle_service.reload_app.assert_any_call("reload_app")
        lifecycle_service.start_app.assert_called_once_with("new_app")


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


class TestReloadApp:
    async def test_rejects_before_stopping_when_unreleased(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
    ) -> None:
        """REJECT_IF_UNRELEASED fails immediately and retains no waiting task."""
        mock_hassette.app_bootstrap_coordinator.is_released.return_value = False
        lifecycle_service._stop_app_unlocked = AsyncMock()
        lifecycle_service._start_app_unlocked = AsyncMock()

        with pytest.raises(AppBootstrapNotReleasedError):
            await lifecycle_service.reload_app("test_app")

        mock_hassette.app_bootstrap_coordinator.wait_released.assert_not_awaited()

        lifecycle_service._stop_app_unlocked.assert_not_called()
        lifecycle_service._start_app_unlocked.assert_not_called()

    async def test_stops_then_starts(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Stops the existing instances (via the unlocked body) then starts new ones."""
        mock_registry.unregister_app = Mock(return_value=None)
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})

        await lifecycle_service.reload_app("test_app")

        mock_registry.unregister_app.assert_called_once_with("test_app")
        mock_factory.create_instances.assert_called_once()


class TestReloadAppLocking:
    async def test_reload_app_acquires_app_key_lock_once(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """reload_app acquires the per-app-key lock exactly once for the whole stop+start
        sequence, rather than each half separately acquiring it. This is a deadlock guard: if
        reload_app instead called the public, lock-acquiring stop_app()/start_app() from
        inside its own lock acquisition, the second acquire would hang forever on the
        non-reentrant asyncio.Lock — asyncio.wait_for below turns that hang into a test
        failure instead of a stuck test run.
        """
        mock_registry.unregister_app = Mock(return_value=None)
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})

        lock = lifecycle_service._get_app_key_lock("test_app")
        lock.acquire = AsyncMock(wraps=lock.acquire)

        await asyncio.wait_for(lifecycle_service.reload_app("test_app"), timeout=1)

        assert lock.acquire.call_count == 1
        assert not lock.locked()

    async def test_concurrent_reload_app_calls_serialize_the_whole_stop_and_start_pair(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """Two concurrent reload_app("x") calls — e.g. a UI reload racing a file-watcher
        reload for the same app_key (issue #1227) — must run each call's full stop+start
        sequence as one atomic unit. `test_reload_app_acquires_app_key_lock_once` proves a
        single reload_app acquires the lock once; this proves a *second*, concurrent
        reload_app for the same key is genuinely blocked until the first's entire
        stop+start pair has completed — not just serialized within start_app's own
        internals, which is the gap #1227 originally described (the second racer's
        create_instances() overwriting the registry entry the first racer just created,
        orphaning a live, already-initialized instance set).
        """
        mock_registry.get_manifest = Mock(return_value=mock_manifest)

        gate = asyncio.Event()
        first_entered = asyncio.Event()
        call_order: list[str] = []

        async def gated_stop_unlocked(_app_key: str) -> None:
            call_order.append("stop_start")
            if call_order.count("stop_start") == 1:
                first_entered.set()
                await gate.wait()
            call_order.append("stop_end")

        async def recording_start_unlocked(_app_key: str, _app_manifest: MagicMock, _force_reload: bool) -> None:
            await asyncio.sleep(0)
            call_order.append("start")

        lifecycle_service._admit_start = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._stop_app_unlocked = gated_stop_unlocked  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._start_app_unlocked = recording_start_unlocked  # pyright: ignore[reportAttributeAccessIssue]

        task1 = asyncio.create_task(lifecycle_service.reload_app("test_app"))
        await asyncio.wait_for(first_entered.wait(), timeout=1)

        task2 = asyncio.create_task(lifecycle_service.reload_app("test_app"))
        lock = lifecycle_service._get_app_key_lock("test_app")
        await wait_for(lambda: bool(lock._waiters), desc="task2 queued on the app-key lock")

        # task2 must be blocked acquiring the lock — it must not have entered its own
        # stop phase while task1's stop+start pair is still mid-flight.
        assert lock.locked()
        assert call_order.count("stop_start") == 1
        assert not task2.done()

        gate.set()
        await asyncio.wait_for(task1, timeout=1)
        await asyncio.wait_for(task2, timeout=1)

        # Each reload's stop and start run back-to-back, and the second reload's stop
        # only starts after the first reload's start has finished — proving the lock
        # covers the entire pair, not just one half of it.
        assert call_order == ["stop_start", "stop_end", "start", "stop_start", "stop_end", "start"]
        assert not lock.locked()


class TestApplyChangesPerInstanceRestart:
    """Per-instance selective restart in apply_changes()'s reload_apps handling (design doc
    "Data flow for selective restart").
    """

    async def test_only_changed_instance_reloads_when_list_length_unchanged(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """A 2-instance app where only instance 1's config changes reloads only
        instance 1 — ``shutdown_instance`` is called only for instance 1, and
        ``create_single_instance`` is called only for index 1.
        """
        old_manifest = MagicMock()
        old_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b", "off_delay": 10}]
        new_manifest = MagicMock()
        new_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b", "off_delay": 30}]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())
        mock_registry.get_manifest = Mock(return_value=new_manifest)
        mock_registry.get_failed_instance_infos = Mock(return_value={})
        mock_registry.get = Mock(return_value=None)

        app1 = MagicMock()

        def unregister_side_effect(_app_key: str, index: int | None = None) -> dict[int, object] | None:
            if index == 1:
                return {1: app1}
            return None

        mock_registry.unregister_app = Mock(side_effect=unregister_side_effect)

        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service.shutdown_instance = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        # Only index 1 was ever unregistered/stopped — index 0 is never touched.
        mock_registry.unregister_app.assert_called_once_with("app_a", 1)
        lifecycle_service.shutdown_instance.assert_called_once_with(app1, instance_index=1)

        # Only index 1 was ever (re)created.
        mock_factory.create_single_instance.assert_called_once()
        # create_single_instance(app_key, manifest, index, config_dict, app_class) — index is arg[2]
        assert mock_factory.create_single_instance.call_args.args[2] == 1

    async def test_reimport_reloads_all_instances_via_reload_app_not_reload_instance(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """A file-level change (reimport_apps bucket) reloads the whole app key via
        ``reload_app``, never the per-instance ``reload_instance``/``_reload_instance_unlocked``
        path — regardless of any per-instance config diff.
        """
        mock_registry.get_manifest = Mock(return_value=MagicMock())
        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service.reload_app = AsyncMock()
        lifecycle_service._reload_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset({"app_a"}),
            reload_apps=frozenset(),
        )

        # original/current configs are irrelevant to the reimport_apps branch — it always does
        # a full reload, so pass configs that (if they leaked into the reload_apps branch) would
        # show a per-instance diff, proving reimport truly bypasses that path.
        old_manifest = MagicMock(app_config=[{"instance_name": "a"}])
        new_manifest = MagicMock(app_config=[{"instance_name": "a-changed"}])

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        lifecycle_service.reload_app.assert_called_once_with("app_a", force_reload=True)
        lifecycle_service._reload_instance_unlocked.assert_not_called()

    async def test_instance_count_change_falls_back_to_full_reload_app(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """When the instance list length changes between old and new config, the
        system falls back to a full ``reload_app`` instead of per-instance reload.
        """
        old_manifest = MagicMock()
        old_manifest.app_config = [{"instance_name": "a"}]
        new_manifest = MagicMock()
        new_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b"}]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.get_manifest = Mock(return_value=new_manifest)

        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service.reload_app = AsyncMock()
        lifecycle_service._reload_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        lifecycle_service.reload_app.assert_called_once_with("app_a")
        lifecycle_service._reload_instance_unlocked.assert_not_called()

    async def test_failure_reloading_one_instance_does_not_block_remaining_instances(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """A 3-instance app where indices 0, 1, and 2 all changed config: if reloading index 0
        raises, indices 1 and 2 must still be attempted, and the exception must not escape
        ``apply_changes()`` (see code review finding — per-index try/except around the batch
        reload loop in ``_reload_app_or_changed_instances``).
        """
        old_manifest = MagicMock()
        old_manifest.app_config = [
            {"instance_name": "a"},
            {"instance_name": "b"},
            {"instance_name": "c"},
        ]
        new_manifest = MagicMock()
        new_manifest.app_config = [
            {"instance_name": "a", "off_delay": 1},
            {"instance_name": "b", "off_delay": 2},
            {"instance_name": "c", "off_delay": 3},
        ]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.get_manifest = Mock(return_value=new_manifest)

        lifecycle_service.should_auto_reconcile = Mock(return_value=True)

        reloaded_indices: list[int] = []

        async def reload_side_effect(_app_key: str, index: int, _force_reload: bool = False) -> None:
            reloaded_indices.append(index)
            if index == 0:
                raise RuntimeError("boom")

        lifecycle_service._reload_instance_unlocked = AsyncMock(side_effect=reload_side_effect)  # pyright: ignore[reportAttributeAccessIssue]

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )

        # Must not raise — the failure at index 0 is caught and logged, not propagated.
        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        # All three indices were attempted despite index 0's failure.
        assert reloaded_indices == [0, 1, 2]

    async def test_batch_reload_runs_instances_concurrently_not_sequentially(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """The batch loop uses asyncio.gather, not a sequential await-per-index loop (ship-time
        challenge finding — sequential processing held the per-app-key lock for the sum of
        every changed instance's timeout). Proven deterministically: index 1 must reach its
        reload before index 0's reload releases, which is only possible if both are running
        concurrently under the same lock acquisition.
        """
        old_manifest = MagicMock()
        old_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b"}]
        new_manifest = MagicMock()
        new_manifest.app_config = [
            {"instance_name": "a", "off_delay": 1},
            {"instance_name": "b", "off_delay": 2},
        ]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.get_manifest = Mock(return_value=new_manifest)
        lifecycle_service.should_auto_reconcile = Mock(return_value=True)

        index_0_entered = asyncio.Event()
        index_0_release = asyncio.Event()
        index_1_entered = asyncio.Event()

        async def reload_side_effect(_app_key: str, index: int, _force_reload: bool = False) -> None:
            if index == 0:
                index_0_entered.set()
                await index_0_release.wait()
            else:
                index_1_entered.set()

        lifecycle_service._reload_instance_unlocked = AsyncMock(side_effect=reload_side_effect)  # pyright: ignore[reportAttributeAccessIssue]

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )
        task = asyncio.create_task(
            lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})
        )

        await asyncio.wait_for(index_0_entered.wait(), timeout=1)
        # If index 1 only starts after index 0 releases, this would deadlock — the whole point
        # of the assertion is that index 1 reaches its reload while index 0 is still blocked.
        await asyncio.wait_for(index_1_entered.wait(), timeout=1)
        assert not task.done()  # index 0 is still parked on its release event

        index_0_release.set()
        await asyncio.wait_for(task, timeout=1)

    async def test_should_auto_reconcile_wraps_the_entire_per_instance_branch(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """A config edit to one instance of a currently-dormant autostart=false app must not
        start any instance — should_auto_reconcile gates the whole per-instance branch, not just
        individual _reload_instance_unlocked() calls.
        """
        old_manifest = MagicMock()
        old_manifest.app_config = [{"instance_name": "a"}]
        new_manifest = MagicMock()
        new_manifest.app_config = [{"instance_name": "a-changed"}]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.get_manifest = Mock(return_value=new_manifest)

        lifecycle_service.should_auto_reconcile = Mock(return_value=False)
        lifecycle_service.reload_app = AsyncMock()
        lifecycle_service._reload_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        lifecycle_service.reload_app.assert_not_called()
        lifecycle_service._reload_instance_unlocked.assert_not_called()


class TestReloadInstanceEvents:
    async def test_reload_instance_emits_state_event_scoped_to_failed_index(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Per-instance reload emits a HassetteAppStateEvent with the correct
        instance identity (app_key, index, instance_name) for the target index only.
        """
        event_capture.install(mock_hassette)
        mock_manifest.app_config = [{"instance_name": "inst_0"}, {"instance_name": "inst_1"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.unregister_app = Mock(return_value=None)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=None)
        load_error = ValueError("boom")
        mock_factory.get_load_error = Mock(return_value=load_error)

        failure_info = AppInstanceInfo(
            app_key="app_a",
            index=1,
            instance_name="inst_1",
            class_name="TestApp",
            status=ResourceStatus.FAILED,
            error=load_error,
            error_message="boom",
            error_traceback="Traceback...",
        )
        mock_registry.get_failed_instance_infos = Mock(return_value={1: failure_info})

        await lifecycle_service.reload_instance("app_a", 1)

        mock_registry.record_failure.assert_called_once_with("app_a", 1, load_error)

        failed_payloads = [
            payload
            for payload in event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED)
            if payload.status == ResourceStatus.FAILED
        ]
        assert len(failed_payloads) == 1
        payload = failed_payloads[0]
        assert payload.app_key == "app_a"
        assert payload.index == 1
        assert payload.instance_name == "inst_1"


class TestStopInstanceFailure:
    async def test_unregister_failure_does_not_raise(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """An exception from registry.unregister_app is caught and logged, not propagated.

        Mirrors TestStopAppFailure.test_unregister_failure_does_not_raise
        (test_app_lifecycle_service_coverage.py) but for the per-instance path — proves
        _stop_instance_unlocked's try/except containment (added in the previous fixer pass)
        actually works.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.unregister_app = Mock(side_effect=RuntimeError("registry corrupted"))
        lifecycle_service.shutdown_instances = AsyncMock()

        await lifecycle_service.stop_instance("test_app", 0)  # must not raise

        lifecycle_service.shutdown_instances.assert_not_called()


class TestStopInstanceBehavior:
    async def test_stops_running_instance_at_target_index(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """stop_instance unregisters and shuts down the running instance at the target
        index only.
        """
        mock_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_failed_instance_infos = Mock(return_value={})
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        app1 = MagicMock()
        mock_registry.unregister_app = Mock(return_value={1: app1})
        lifecycle_service.shutdown_instances = AsyncMock()

        await lifecycle_service.stop_instance("test_app", 1)

        mock_registry.unregister_app.assert_called_once_with("test_app", 1)
        lifecycle_service.shutdown_instances.assert_called_once_with({1: app1})

    async def test_out_of_range_index_skips_cleanly(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """stop_instance no-ops for an index beyond the current manifest's instance count."""
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.unregister_app = Mock()

        await lifecycle_service.stop_instance("test_app", 5)

        mock_registry.unregister_app.assert_not_called()

    async def test_succeeds_without_admission_check_before_bootstrap_release(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """stop_instance does not call _admit_start — it works before bootstrap release,
        matching the existing stop_app convention (design.md Edge Cases: "The stop endpoint
        does not go through admission").
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_failed_instance_infos = Mock(return_value={})
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.unregister_app = Mock(return_value={})
        lifecycle_service._admit_start = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service.stop_instance("test_app", 0)

        lifecycle_service._admit_start.assert_not_called()


class TestStartInstanceFailure:
    async def test_create_instance_failure_does_not_raise(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """An exception from create_single_instance is caught and logged, not propagated.

        Mirrors TestStopInstanceFailure.test_unregister_failure_does_not_raise but for
        start_instance — proves the try/except containment around its lock body (added in
        the ship-time challenge fixer pass) actually works, matching _start_app_unlocked's
        existing containment for the full app-key path.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())
        mock_factory.create_single_instance = Mock(side_effect=RuntimeError("factory blew up"))

        await lifecycle_service.start_instance("test_app", 0)  # must not raise


class TestStartInstanceBehavior:
    async def test_creates_and_initializes_target_index(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """start_instance creates and initializes the instance at the target index only."""
        mock_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())
        mock_registry.get_failed_instance_infos = Mock(return_value={})
        mock_registry.get = Mock(return_value=None)

        await lifecycle_service.start_instance("test_app", 1)

        mock_factory.create_single_instance.assert_called_once()
        # create_single_instance(app_key, manifest, index, config_dict, app_class) — index is arg[2]
        assert mock_factory.create_single_instance.call_args.args[2] == 1

    async def test_already_running_index_skips_without_recreating(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
        mock_app_instance: MagicMock,
    ) -> None:
        """start_instance no-ops when the target index already has a running instance, rather
        than overwriting the registry entry and leaking the original instance's listeners,
        scheduler jobs, and tasks (ship-time review finding — register_app() silently replaces
        any prior entry at that index).
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.get = Mock(return_value=mock_app_instance)

        await lifecycle_service.start_instance("test_app", 0)

        mock_factory.create_single_instance.assert_not_called()

    async def test_out_of_range_index_skips_cleanly(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """start_instance no-ops for an index beyond the current manifest's instance count."""
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)

        await lifecycle_service.start_instance("test_app", 5)

        mock_factory.create_single_instance.assert_not_called()

    async def test_negative_index_skips_cleanly(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """start_instance no-ops for a negative index rather than resolving it via Python's
        negative-indexing semantics into the last configured instance (ship-time challenge
        finding — the shared _instance_index_in_range() helper only checked the upper bound).
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)

        await lifecycle_service.start_instance("test_app", -1)

        mock_factory.create_single_instance.assert_not_called()


class TestPerInstanceLifecycleLocking:
    async def test_reload_instance_acquires_app_key_lock_once(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """reload_instance acquires the per-app-key lock exactly once."""
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)

        lock = lifecycle_service._get_app_key_lock("test_app")
        lock.acquire = AsyncMock(wraps=lock.acquire)
        lifecycle_service._reload_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await asyncio.wait_for(lifecycle_service.reload_instance("test_app", 0), timeout=1)

        assert lock.acquire.call_count == 1
        assert not lock.locked()

    async def test_stop_instance_acquires_app_key_lock_once(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """stop_instance acquires the per-app-key lock exactly once."""
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.unregister_app = Mock(return_value=None)
        mock_registry.get_failed_instance_infos = Mock(return_value={})

        lock = lifecycle_service._get_app_key_lock("test_app")
        lock.acquire = AsyncMock(wraps=lock.acquire)

        await asyncio.wait_for(lifecycle_service.stop_instance("test_app", 0), timeout=1)

        assert lock.acquire.call_count == 1
        assert not lock.locked()

    async def test_start_instance_acquires_app_key_lock_once(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """start_instance acquires the per-app-key lock exactly once."""
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=None)
        mock_factory.get_load_error = Mock(return_value=ValueError("boom"))
        mock_registry.get_failed_instance_infos = Mock(return_value={})

        lock = lifecycle_service._get_app_key_lock("test_app")
        lock.acquire = AsyncMock(wraps=lock.acquire)

        await asyncio.wait_for(lifecycle_service.start_instance("test_app", 0), timeout=1)

        assert lock.acquire.call_count == 1
        assert not lock.locked()

    async def test_reload_instance_serializes_with_concurrent_reload_app(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """A per-instance reload and a full app-key reload for the same app_key must
        not run concurrently — both acquire the same per-app-key lock, so a full app-key
        operation queued behind an in-flight per-instance operation stays blocked until it
        completes.
        """
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})

        gate = asyncio.Event()
        first_entered = asyncio.Event()
        call_order: list[str] = []

        async def gated_reload_instance_unlocked(_app_key: str, _index: int, _force_reload: bool = False) -> None:
            call_order.append("instance_start")
            first_entered.set()
            await gate.wait()
            call_order.append("instance_end")

        async def recording_stop_unlocked(_app_key: str) -> None:
            call_order.append("stop")

        async def recording_start_unlocked(_app_key: str, _app_manifest: MagicMock, _force_reload: bool) -> None:
            call_order.append("start")

        lifecycle_service._reload_instance_unlocked = gated_reload_instance_unlocked  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._stop_app_unlocked = recording_stop_unlocked  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._start_app_unlocked = recording_start_unlocked  # pyright: ignore[reportAttributeAccessIssue]

        task1 = asyncio.create_task(lifecycle_service.reload_instance("test_app", 0))
        await asyncio.wait_for(first_entered.wait(), timeout=1)

        task2 = asyncio.create_task(lifecycle_service.reload_app("test_app"))
        lock = lifecycle_service._get_app_key_lock("test_app")
        await wait_for(lambda: bool(lock._waiters), desc="reload_app queued on the app-key lock")

        assert lock.locked()
        assert call_order == ["instance_start"]
        assert not task2.done()

        gate.set()
        await asyncio.wait_for(task1, timeout=1)
        await asyncio.wait_for(task2, timeout=1)

        assert call_order == ["instance_start", "instance_end", "stop", "start"]
        assert not lock.locked()


class TestReconcileBlockedApps:
    def test_blocks_non_only_apps(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Blocks all apps except the ones in the exclusive-app filter."""
        mock_registry.only_apps = frozenset({"app_a"})
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock(), "app_c": MagicMock()}
        mock_registry.unblock_apps = Mock(return_value=set())

        lifecycle_service.reconcile_blocked_apps()

        block_calls = mock_registry.block_app.call_args_list
        blocked_keys = {call[0][0] for call in block_calls}
        assert blocked_keys == {"app_b", "app_c"}
        for call in block_calls:
            assert call[0][1] == BlockReason.ONLY_APP

    def test_keeps_every_app_in_a_multi_key_filter(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """`--app a --app b` blocks only the apps outside the filter."""
        mock_registry.only_apps = frozenset({"app_a", "app_b"})
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock(), "app_c": MagicMock()}
        mock_registry.unblock_apps = Mock(return_value=set())

        lifecycle_service.reconcile_blocked_apps()

        blocked_keys = {call[0][0] for call in mock_registry.block_app.call_args_list}
        assert blocked_keys == {"app_c"}

    def test_unblocks_when_only_apps_cleared(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Unblocks previously blocked apps when the exclusive-app filter is empty."""
        mock_registry.only_apps = frozenset()
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock()}
        mock_registry.unblock_apps = Mock(return_value={"app_b"})

        result = lifecycle_service.reconcile_blocked_apps()

        mock_registry.unblock_apps.assert_called_once_with(BlockReason.ONLY_APP)
        mock_registry.block_app.assert_not_called()
        assert result == {"app_b"}


class TestResolveOnlyApps:
    async def test_config_keys_set_the_filter(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Every requested key that names an enabled app becomes the filter."""
        mock_hassette.config.only_apps = ("app_a", "app_b")
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock(), "app_c": MagicMock()}

        await lifecycle_service.resolve_only_apps()

        mock_registry.set_only_apps.assert_called_with({"app_a", "app_b"})

    async def test_unknown_key_still_filters_everything_out(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """A mistyped key matches no app rather than silently starting all of them."""
        mock_hassette.config.only_apps = ("app_typo",)
        mock_registry.enabled_manifests = {"app_a": MagicMock()}

        await lifecycle_service.resolve_only_apps()

        mock_registry.set_only_apps.assert_called_with({"app_typo"})

    async def test_honored_in_prod_mode(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """The --app flag works in both dev and production mode."""
        mock_hassette.config.dev_mode = False
        mock_hassette.config.only_apps = ("app_a",)
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock()}

        await lifecycle_service.resolve_only_apps()

        mock_registry.set_only_apps.assert_called_with({"app_a"})


class TestRefreshConfig:
    async def test_reloads_config_and_returns_before_after(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """Calls config.reload() and returns original and current manifests."""
        manifest1 = MagicMock()
        manifest1.enabled = True
        mock_registry.manifests = {"app_a": manifest1}
        mock_hassette.config.apps.manifests = {"app_a": manifest1}
        reload_mock = Mock()
        object.__setattr__(mock_hassette.config, "reload", reload_mock)

        original, current = await lifecycle_service.refresh_config()

        reload_mock.assert_called_once()
        assert "app_a" in original
        assert "app_a" in current


class TestReconcileAppRegistrations:
    """Tests for reconcile_app_registrations — the post-ready reconciliation helper."""

    async def test_reconcile_calls_reconcile_registrations(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_app_instance: AsyncMock,
    ) -> None:
        """reconcile_registrations() is called with live IDs after barriers complete."""
        instances = {0: mock_app_instance}
        await lifecycle_service.reconcile_app_registrations("test_app", instances)

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

        await lifecycle_service.reconcile_app_registrations("test_app", instances)


class TestSetAppsConfigs:
    def test_sets_manifests_on_registry(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls registry.set_manifests with the provided config."""
        manifests = {"app_a": MagicMock()}

        lifecycle_service.set_apps_configs(manifests)

        mock_registry.set_manifests.assert_called_once()
        mock_registry.set_only_apps.assert_called_with(())


class TestPersistManifests:
    """Tests for persist_manifests() — the per-item-isolated manifest upsert trigger."""

    async def test_upserts_every_manifest_in_registry(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """Calls command_executor.upsert_app_manifest once per manifest currently in the registry."""
        manifest_a = MagicMock()
        manifest_b = MagicMock()
        mock_registry.manifests = {"app_a": manifest_a, "app_b": manifest_b}
        mock_hassette.command_executor.upsert_app_manifest = AsyncMock()

        await lifecycle_service.persist_manifests()

        mock_hassette.command_executor.upsert_app_manifest.assert_any_call(manifest_a)
        mock_hassette.command_executor.upsert_app_manifest.assert_any_call(manifest_b)
        assert mock_hassette.command_executor.upsert_app_manifest.await_count == 2

    async def test_one_failure_does_not_block_remaining_upserts(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """A failed upsert is isolated — the remaining manifests still get persisted, and the
        failure never propagates out of persist_manifests() to the bootstrap/reload caller.
        """
        manifest_a = MagicMock()
        manifest_b = MagicMock()
        mock_registry.manifests = {"app_a": manifest_a, "app_b": manifest_b}
        mock_hassette.command_executor.upsert_app_manifest = AsyncMock(side_effect=[RuntimeError("DB full"), 1])

        await lifecycle_service.persist_manifests()

        assert mock_hassette.command_executor.upsert_app_manifest.await_count == 2

    async def test_upserts_run_concurrently_not_sequentially(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """A sequential loop would hang here: each upsert only returns once *both* are in
        flight, so a sequential implementation would await the first call forever — surfaced
        by `asyncio.wait_for` below as a `TimeoutError` rather than an actual hang. Deterministic
        per CLAUDE.md's startup-race pattern — no sleep-based timing races.
        """
        both_in_flight = asyncio.Event()
        in_flight_count = 0

        async def blocking_upsert(_manifest: object) -> None:
            nonlocal in_flight_count
            in_flight_count += 1
            if in_flight_count == 2:
                both_in_flight.set()
            await both_in_flight.wait()

        mock_registry.manifests = {"app_a": MagicMock(), "app_b": MagicMock()}
        mock_hassette.command_executor.upsert_app_manifest = AsyncMock(side_effect=blocking_upsert)

        await asyncio.wait_for(lifecycle_service.persist_manifests(), timeout=1)

        assert in_flight_count == 2


class TestCreateInstanceUnlockedSynchronousFailure:
    async def test_returns_early_without_initializing_when_create_single_instance_fails_synchronously(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """create_single_instance() can register a failure synchronously (e.g. a config
        validation error at instance-creation time, not a class-load error) without raising.
        _create_instance_unlocked must notice that recorded failure via
        _emit_failure_event_if_present and return early rather than proceeding to
        initialize_instances().
        """
        event_capture.install(mock_hassette)
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())

        failure_info = AppInstanceInfo(
            app_key="test_app",
            index=0,
            instance_name="test_app.0",
            class_name="TestApp",
            status=ResourceStatus.FAILED,
            error=ValueError("bad config"),
            error_message="bad config",
            error_traceback="Traceback...",
        )
        mock_registry.get_failed_instance_infos = Mock(return_value={0: failure_info})

        lifecycle_service.initialize_instances = AsyncMock()

        await lifecycle_service._create_instance_unlocked("test_app", 0, mock_manifest)

        mock_factory.create_single_instance.assert_called_once()
        lifecycle_service.initialize_instances.assert_not_called()

        failed_payloads = [
            payload
            for payload in event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED)
            if payload.status == ResourceStatus.FAILED
        ]
        assert len(failed_payloads) == 1


class TestReloadInstanceUnlockedGuards:
    async def test_unknown_app_key_returns_without_stopping_or_creating(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """Unknown/missing app_key (manifest is None after get_manifest) logs and returns
        without stopping or creating anything.
        """
        mock_registry.get_manifest = Mock(return_value=None)
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._create_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service._reload_instance_unlocked("missing_app", 0)

        lifecycle_service._stop_instance_unlocked.assert_not_called()
        lifecycle_service._create_instance_unlocked.assert_not_called()

    async def test_index_out_of_range_returns_without_stopping_or_creating(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Index beyond the current manifest's instance count returns without stopping or
        creating anything.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._create_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service._reload_instance_unlocked("test_app", 5)

        lifecycle_service._stop_instance_unlocked.assert_not_called()
        lifecycle_service._create_instance_unlocked.assert_not_called()


class TestReloadInstanceFailure:
    async def test_reload_instance_unlocked_failure_does_not_raise(
        self,
        lifecycle_service: AppLifecycleService,
    ) -> None:
        """If _reload_instance_unlocked raises inside the lock body, the public
        reload_instance() catches it and logs rather than propagating — mirrors
        TestReloadAppFailure.test_stop_failure_prevents_start_and_does_not_raise
        (test_app_lifecycle_service_coverage.py) but for the per-instance path.
        """
        lifecycle_service._reload_instance_unlocked = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
            side_effect=RuntimeError("boom")
        )

        await lifecycle_service.reload_instance("test_app", 0)  # must not raise

        lifecycle_service._reload_instance_unlocked.assert_awaited_once_with("test_app", 0, False)


class TestStopInstanceUnlockedShutdownFailure:
    async def test_shutdown_instances_failure_does_not_raise(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """An exception raised by shutdown_instances() (as opposed to unregister_app, already
        covered by TestStopInstanceFailure.test_unregister_failure_does_not_raise) is also
        caught and logged by the same try/except in _stop_instance_unlocked.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_failed_instance_infos = Mock(return_value={})
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        app1 = MagicMock()
        mock_registry.unregister_app = Mock(return_value={0: app1})
        lifecycle_service.shutdown_instances = AsyncMock(side_effect=RuntimeError("shutdown blew up"))

        await lifecycle_service.stop_instance("test_app", 0)  # must not raise

        lifecycle_service.shutdown_instances.assert_awaited_once()


class TestStartInstanceAdmissionGuards:
    async def test_unknown_app_key_skips_before_admission_check(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """Missing/unknown manifest returns before _admit_start is even called — the first
        `if not app_manifest: return` guard near the top of start_instance().
        """
        mock_registry.get_manifest = Mock(return_value=None)
        lifecycle_service._admit_start = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service.start_instance("test_app", 0)

        lifecycle_service._admit_start.assert_not_called()

    async def test_manifest_removed_during_admission_wait_skips_post_lock_creation(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """A manifest removed while start_instance() is parked in _admit_start() must not be
        used for the post-lock re-fetch — mirrors start_app()'s equivalent race guard
        (TestStartAppStaleManifestRace.test_manifest_removed_during_admission_wait_is_not_used).
        """
        mock_registry.get_manifest = Mock(side_effect=[mock_manifest, None])
        lifecycle_service._admit_start = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._create_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service.start_instance("test_app", 0)

        lifecycle_service._admit_start.assert_awaited_once()
        lifecycle_service._create_instance_unlocked.assert_not_called()
