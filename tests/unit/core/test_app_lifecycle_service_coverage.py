"""Unit tests filling coverage gaps in AppLifecycleService.

Complements test_app_lifecycle_service.py (init/properties/initialize/shutdown/bootstrap/
apply-changes gating) and test_app_lifecycle_service_operations.py (start/stop/reload/
resolve_only_apps/refresh_config/reconcile). This file targets the remaining branches:
specific factory exceptions, stop/reload failure paths, start_apps error aggregation,
handle_change_event's unblock-and-no-op branches, resolve_only_apps's error/prod/multi-only
paths, and reconcile_app_registrations' degraded-mode fallbacks.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, seal

from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppAdmissionMode, AppLifecycleService, PendingReconciliation
from hassette.exceptions import InvalidInheritanceError, UndefinedUserConfigError
from hassette.test_utils import EventCapture, wait_for
from hassette.types import Topic

from .conftest import set_registry_apps


class TestBootstrapAppsSuccessLogging:
    async def test_emits_load_completed_when_apps_running(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """The successful-initialization branch (running_count > 0) still emits APP_LOAD_COMPLETED."""
        event_capture.install(mock_hassette)
        mock_registry.manifests = {"app_a": MagicMock()}
        mock_registry.active_manifests = {}
        mock_registry.get_snapshot = Mock(return_value=MagicMock(running_count=1, failed_count=0))

        await lifecycle_service.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

        completed_calls = event_capture.by_topic(Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED)
        assert len(completed_calls) == 1


class TestStartAppSpecificFactoryErrors:
    async def test_undefined_user_config_error_skips_start(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """UndefinedUserConfigError from factory.create_instances is caught; no instances started."""
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.create_instances.side_effect = UndefinedUserConfigError("no user_config_class")

        await lifecycle_service.start_app("test_app")

        mock_registry.get_apps_by_key.assert_not_called()

    async def test_invalid_inheritance_error_skips_start(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """InvalidInheritanceError from factory.create_instances is caught; no instances started."""
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.create_instances.side_effect = InvalidInheritanceError("bad base class")

        await lifecycle_service.start_app("test_app")

        mock_registry.get_apps_by_key.assert_not_called()


class TestStopAppFailure:
    async def test_unregister_failure_does_not_raise(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """An exception from registry.unregister_app is caught and logged, not propagated."""
        mock_registry.unregister_app = Mock(side_effect=RuntimeError("registry corrupted"))
        lifecycle_service.shutdown_instances = AsyncMock()

        await lifecycle_service.stop_app("test_app")

        lifecycle_service.shutdown_instances.assert_not_called()


class TestReloadAppFailure:
    async def test_stop_failure_prevents_start_and_does_not_raise(self, lifecycle_service: AppLifecycleService) -> None:
        """If stop_app raises, reload_app catches it and never calls start_app."""
        lifecycle_service.stop_app = AsyncMock(side_effect=RuntimeError("stop blew up"))
        lifecycle_service.start_app = AsyncMock()

        await lifecycle_service.reload_app("test_app")

        lifecycle_service.start_app.assert_not_called()


class TestStartAppsErrorAggregation:
    async def test_one_app_failing_does_not_block_others(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """gather(..., return_exceptions=True) lets other app starts proceed after one raises."""
        manifest_a = MagicMock()
        manifest_b = MagicMock()
        mock_registry.autostart_manifests = {"app_a": manifest_a, "app_b": manifest_b}
        mock_registry.get_manifest = Mock(side_effect=lambda k: {"app_a": manifest_a, "app_b": manifest_b}.get(k))

        started: list[str] = []

        async def fake_start_app(app_key: str, *, admission_mode: AppAdmissionMode) -> None:
            assert admission_mode is AppAdmissionMode.REJECT_IF_UNRELEASED
            if app_key == "app_a":
                raise RuntimeError("app_a exploded")
            started.append(app_key)

        lifecycle_service.start_app = fake_start_app  # pyright: ignore[reportAttributeAccessIssue]

        # Should not raise despite app_a's failure.
        await lifecycle_service.start_apps()

        assert started == ["app_b"]


class TestHandleChangeEventBranches:
    async def test_no_changes_returns_without_applying_or_emitting(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """When detect_changes reports no changes, apply_changes is skipped and no event fires."""
        event_capture.install(mock_hassette)
        lifecycle_service.change_detector.detect_changes = Mock(  # pyright: ignore[reportAttributeAccessIssue]
            return_value=ChangeSet(
                orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset()
            )
        )
        lifecycle_service.apply_changes = AsyncMock()

        await lifecycle_service.handle_change_event()

        lifecycle_service.apply_changes.assert_not_called()
        completed_calls = event_capture.by_topic(Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED)
        assert len(completed_calls) == 0

    async def test_unblocked_apps_are_folded_into_new_apps(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Apps unblocked by reconcile_blocked_apps (and not already running/changing) are started."""
        event_capture.install(mock_hassette)
        lifecycle_service.change_detector.detect_changes = Mock(  # pyright: ignore[reportAttributeAccessIssue]
            return_value=ChangeSet(
                orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset()
            )
        )
        lifecycle_service.reconcile_blocked_apps = Mock(return_value={"unblocked_app"})
        set_registry_apps(mock_registry, {})

        applied: list[ChangeSet] = []

        async def capture_apply(changes: ChangeSet) -> None:
            applied.append(changes)

        lifecycle_service.apply_changes = capture_apply  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service.handle_change_event()

        assert len(applied) == 1
        assert applied[0].new_apps == frozenset({"unblocked_app"})

        completed_calls = event_capture.by_topic(Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED)
        assert len(completed_calls) == 1

    async def test_pre_release_changes_are_deferred_and_coalesced(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        event_capture.install(mock_hassette)
        mock_hassette.app_bootstrap_coordinator.is_released.return_value = False
        lifecycle_service.change_detector.detect_changes = Mock(  # pyright: ignore[reportAttributeAccessIssue]
            return_value=ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset({"my_app"}),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )
        )
        lifecycle_service.apply_changes = AsyncMock()

        await lifecycle_service.handle_change_event(changed_file_paths=frozenset({Path("/tmp/first.py")}))
        await lifecycle_service.handle_change_event(changed_file_paths=frozenset({Path("/tmp/second.py")}))

        lifecycle_service.apply_changes.assert_not_called()
        pending = lifecycle_service._pending_reconciliation
        assert pending is not None
        assert pending.original_apps_config is not None
        assert pending.current_apps_config is not None
        assert pending.changed_paths == frozenset({Path("/tmp/first.py"), Path("/tmp/second.py")})
        assert event_capture.by_topic(Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED) == []

    async def test_stale_pre_release_diff_is_merged_into_post_release_change(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
    ) -> None:
        """A pre-release reconciliation still queued when release opens must be folded into
        the next post-release diff's baseline and paths (not dropped, not left to be replayed
        later as a stale standalone diff), and the queue must be cleared afterward.
        """
        # Queue a pre-release change while still unreleased.
        mock_hassette.app_bootstrap_coordinator.is_released.return_value = False
        lifecycle_service.change_detector.detect_changes = Mock(  # pyright: ignore[reportAttributeAccessIssue]
            return_value=ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset({"pre_release_app"}),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )
        )
        lifecycle_service.apply_changes = AsyncMock()

        await lifecycle_service.handle_change_event(changed_file_paths=frozenset({Path("/tmp/pre.py")}))

        pending = lifecycle_service._pending_reconciliation
        assert pending is not None
        pending_original_snapshot = pending.original_apps_config
        assert pending_original_snapshot is not None

        # Release opens; a newer post-release change arrives with its own fresh baseline.
        mock_hassette.app_bootstrap_coordinator.is_released.return_value = True

        captured_calls: list[tuple[dict | None, dict | None, frozenset[Path] | None]] = []

        def capture_detect_changes(original, current, changed_paths, **_kwargs):
            captured_calls.append((original, current, changed_paths))
            return ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset({"post_release_app"}),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )

        lifecycle_service.change_detector.detect_changes = capture_detect_changes  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service.apply_changes = AsyncMock()

        await lifecycle_service.handle_change_event(changed_file_paths=frozenset({Path("/tmp/post.py")}))

        # The merge must use the pre-release baseline (not the fresh refresh_config() original
        # from this call) and union the changed paths, proving the queued snapshot was folded
        # into this diff rather than dropped or replayed later on its own.
        assert captured_calls[0][0] is pending_original_snapshot
        assert captured_calls[0][2] == frozenset({Path("/tmp/pre.py"), Path("/tmp/post.py")})

        # The queue is cleared so bootstrap's later replay can't re-apply this stale snapshot.
        assert lifecycle_service._pending_reconciliation is None
        lifecycle_service.apply_changes.assert_awaited_once()

    async def test_concurrent_invocations_are_serialized_by_the_change_event_lock(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """Two overlapping handle_change_event() calls — as the bus's ``parallel`` dispatch
        mode produces when two file-watcher events fire close together (BusService._dispatch
        spawns one task per handler invocation rather than awaiting handlers sequentially) —
        must not run concurrently. Without serialization, the second call's refresh_config()
        could start (and mutate self.registry.manifests) before the first call finishes
        reading it, tearing the "what was the world like before this change" snapshot.
        """
        gate = asyncio.Event()
        first_entered = asyncio.Event()
        call_count = 0
        empty = ChangeSet(orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset())

        async def gated_refresh_config() -> tuple[dict, dict]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_entered.set()
                await gate.wait()
            return {}, {}

        lifecycle_service.refresh_config = gated_refresh_config  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service.resolve_only_apps = AsyncMock()
        lifecycle_service.change_detector.detect_changes = Mock(return_value=empty)  # pyright: ignore[reportAttributeAccessIssue]

        task1 = asyncio.create_task(lifecycle_service.handle_change_event())
        await asyncio.wait_for(first_entered.wait(), timeout=1.0)

        task2 = asyncio.create_task(lifecycle_service.handle_change_event())
        # Deterministically wait until task2 has actually queued on the lock (asyncio.Lock.acquire()
        # appends a waiter future synchronously, before its own await) rather than assuming a single
        # scheduler tick is enough — see CLAUDE.md's "Deterministic Async Race Gate" convention.
        await wait_for(lambda: bool(lifecycle_service._change_event_lock._waiters), desc="task2 queued on the lock")

        # task2 must be blocked acquiring the lock, not yet inside refresh_config.
        assert lifecycle_service._change_event_lock.locked()
        assert call_count == 1
        assert not task2.done()

        gate.set()
        await asyncio.wait_for(task1, timeout=1.0)
        await asyncio.wait_for(task2, timeout=1.0)

        assert call_count == 2


class TestReplayPreReleaseReconciliationSerialization:
    async def test_replay_and_handle_change_event_do_not_race(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """_replay_pre_release_reconciliation_if_needed() (called from bootstrap_apps()) reads and
        clears the same _pending_reconciliation state as handle_change_event(); both must serialize on
        _change_event_lock. Without that, a file-watcher event arriving while bootstrap is replaying
        could race the take/clear of that state.
        """
        gate = asyncio.Event()
        first_entered = asyncio.Event()
        call_count = 0
        empty = ChangeSet(orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset())

        async def gated_resolve_only_apps() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_entered.set()
                await gate.wait()

        lifecycle_service._pending_reconciliation = PendingReconciliation(
            original_apps_config={},
            current_apps_config={},
            changed_paths=None,
        )

        lifecycle_service.resolve_only_apps = gated_resolve_only_apps  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service.refresh_config = AsyncMock(return_value=({}, {}))  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service.change_detector.detect_changes = Mock(return_value=empty)  # pyright: ignore[reportAttributeAccessIssue]

        task1 = asyncio.create_task(lifecycle_service._replay_pre_release_reconciliation_if_needed())
        await asyncio.wait_for(first_entered.wait(), timeout=1.0)

        # The lock-holding take() already ran before the gated await, so the pending state is
        # already cleared even though task1 hasn't finished — proving the take happens inside the lock.
        assert lifecycle_service._pending_reconciliation is None

        task2 = asyncio.create_task(lifecycle_service.handle_change_event())
        # Deterministically wait until task2 has actually queued on the lock (asyncio.Lock.acquire()
        # appends a waiter future synchronously, before its own await) rather than assuming a single
        # scheduler tick is enough — see CLAUDE.md's "Deterministic Async Race Gate" convention.
        await wait_for(lambda: bool(lifecycle_service._change_event_lock._waiters), desc="task2 queued on the lock")

        assert lifecycle_service._change_event_lock.locked()
        assert call_count == 1
        assert not task2.done()

        gate.set()
        await asyncio.wait_for(task1, timeout=1.0)
        await asyncio.wait_for(task2, timeout=1.0)

        assert call_count == 2


class TestRefreshConfigFailure:
    async def test_reload_failure_does_not_raise_and_still_returns_manifests(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """config.reload() raising is caught; refresh_config still returns a valid (original, current) pair."""
        manifest1 = MagicMock()
        manifest1.enabled = True
        mock_registry.manifests = {"app_a": manifest1}
        mock_hassette.config.apps.manifests = {"app_a": manifest1}
        object.__setattr__(mock_hassette.config, "reload", Mock(side_effect=RuntimeError("disk error")))

        original, current = await lifecycle_service.refresh_config()

        assert "app_a" in original
        assert "app_a" in current


class TestReconcileAppRegistrationsDegradedPaths:
    async def test_listener_collection_failure_is_non_fatal(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_app_instance: AsyncMock
    ) -> None:
        """A failure collecting listener IDs from one instance leaves live_listener_ids empty."""
        mock_app_instance.bus.get_listeners = Mock(side_effect=RuntimeError("bus unavailable"))
        instances = {0: mock_app_instance}

        await lifecycle_service.reconcile_app_registrations("test_app", instances)

        call_kwargs = mock_hassette.command_executor.reconcile_registrations.call_args
        assert call_kwargs.args[1] == []

    async def test_router_safety_guard_failure_is_non_fatal(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_app_instance: AsyncMock
    ) -> None:
        """Router guard failure still leaves the directly-collected listener IDs intact."""
        mock_app_instance.bus.get_listeners = Mock(return_value=[MagicMock(db_id=99)])
        mock_hassette.bus_service.router.get_listeners_by_owner = Mock(side_effect=RuntimeError("router down"))
        instances = {0: mock_app_instance}

        await lifecycle_service.reconcile_app_registrations("test_app", instances)

        call_kwargs = mock_hassette.command_executor.reconcile_registrations.call_args
        # Router union failed, but the bus-collected ID (99) survives.
        assert set(call_kwargs.args[1]) == {99}

    async def test_router_safety_guard_unions_listener_ids(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_app_instance: AsyncMock
    ) -> None:
        """Router-known listener IDs are unioned in; a router listener with no db_id is excluded."""
        mock_app_instance.bus.get_listeners = Mock(return_value=[MagicMock(db_id=1)])
        mock_hassette.bus_service.router.get_listeners_by_owner = Mock(
            return_value=[MagicMock(db_id=2), MagicMock(db_id=None)]
        )
        instances = {0: mock_app_instance}

        await lifecycle_service.reconcile_app_registrations("test_app", instances)

        call_kwargs = mock_hassette.command_executor.reconcile_registrations.call_args
        # Bus-collected (1) unioned with router-collected (2); the None-db_id router listener excluded.
        assert set(call_kwargs.args[1]) == {1, 2}

    async def test_job_id_collection_failure_is_non_fatal(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_app_instance: AsyncMock
    ) -> None:
        """A failure collecting job IDs from one instance leaves live_job_ids empty."""
        mock_app_instance.scheduler.get_job_db_ids = Mock(side_effect=RuntimeError("scheduler unavailable"))
        instances = {0: mock_app_instance}

        await lifecycle_service.reconcile_app_registrations("test_app", instances)

        call_kwargs = mock_hassette.command_executor.reconcile_registrations.call_args
        assert call_kwargs.args[2] == []

    async def test_session_id_unavailable_degrades_gracefully(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_app_instance: AsyncMock
    ) -> None:
        """When hassette.session_id access raises, reconciliation proceeds with session_id=None.

        `mock_hassette` is built with `sealed=False`, so `session_id` (set explicitly by the
        fixture) lives in the instance `__dict__`. Deleting it and then sealing the mock makes
        any further access auto-vivify-and-raise `AttributeError` instead of returning a stub
        child mock — the same failure shape production guards against.
        """
        del mock_hassette.session_id
        seal(mock_hassette)
        instances = {0: mock_app_instance}

        await lifecycle_service.reconcile_app_registrations("test_app", instances)

        mock_hassette.command_executor.reconcile_registrations.assert_awaited_once()
        call_kwargs = mock_hassette.command_executor.reconcile_registrations.call_args
        assert call_kwargs.kwargs["session_id"] is None

    async def test_collects_live_listener_and_job_ids(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_app_instance: AsyncMock
    ) -> None:
        """Listener IDs with a db_id are collected; None db_ids are excluded. Job IDs pass through."""
        listener_with_id = MagicMock(db_id=42)
        listener_without_id = MagicMock(db_id=None)
        mock_app_instance.bus.get_listeners = Mock(return_value=[listener_with_id, listener_without_id])
        mock_app_instance.scheduler.get_job_db_ids = Mock(return_value=[7, 8])

        instances = {0: mock_app_instance}

        await lifecycle_service.reconcile_app_registrations("test_app", instances)

        call_kwargs = mock_hassette.command_executor.reconcile_registrations.call_args
        assert set(call_kwargs.args[1]) == {42}
        assert call_kwargs.args[2] == [7, 8]
