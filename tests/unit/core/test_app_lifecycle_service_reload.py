"""Unit tests for AppLifecycleService — change application and reload operations."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.exceptions import AppBootstrapNotReleasedError
from hassette.test_utils import wait_for

from .conftest import set_registry_apps


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
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock(), 1: MagicMock()}})
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
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock()}})
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

    async def test_changed_index_colliding_with_unchanged_sibling_falls_back_to_full_reload(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """When a changed index adopts the instance_name of an unchanged sibling (index 0
        renames a -> b while index 1 stays b), the selective batch reload would leave two live
        instances sharing one App.unique_name — see PR #1687 review finding. Detecting the
        overlap must fall back to a full reload_app instead of the per-index batch reload.
        """
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock(), 1: MagicMock()}})
        old_manifest = MagicMock()
        old_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b"}]
        new_manifest = MagicMock()
        new_manifest.app_config = [{"instance_name": "b"}, {"instance_name": "b"}]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.get_manifest = Mock(return_value=new_manifest)

        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service.reload_app = AsyncMock()
        lifecycle_service._create_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        lifecycle_service.reload_app.assert_called_once_with("app_a")
        # The selective batch-reload path must never run once the overlap is detected — proves
        # the fallback happens before any stop/create, not after a partial batch reload.
        lifecycle_service._create_instance_unlocked.assert_not_called()
        lifecycle_service._stop_instance_unlocked.assert_not_called()

    async def test_two_changed_indices_colliding_with_each_other_falls_back_to_full_reload(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Two *changed* indices adopting the same new instance_name from each other (index 0:
        a -> c, index 1: b -> c) share no name with any unchanged sibling, so the unchanged-vs-
        changed overlap check alone would miss it — but the selective batch reload's create-all
        phase would still create two live instances both deriving App.unique_name "c", the same
        permanent owner-registry collision. Must also fall back to a full reload_app.
        """
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock(), 1: MagicMock()}})
        old_manifest = MagicMock()
        old_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b"}]
        new_manifest = MagicMock()
        new_manifest.app_config = [{"instance_name": "c"}, {"instance_name": "c"}]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.get_manifest = Mock(return_value=new_manifest)

        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service.reload_app = AsyncMock()
        lifecycle_service._create_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        lifecycle_service.reload_app.assert_called_once_with("app_a")
        lifecycle_service._create_instance_unlocked.assert_not_called()
        lifecycle_service._stop_instance_unlocked.assert_not_called()

    async def test_changed_index_with_no_sibling_overlap_takes_selective_reload_path(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """The common case — a changed index's new name doesn't collide with any unchanged
        sibling's current name — must still take the fast selective per-index batch reload, not
        the full reload_app fallback (regression guard for the overlap check above; don't let a
        false-positive overlap detection slow down the normal rename case).
        """
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock(), 1: MagicMock()}})
        old_manifest = MagicMock()
        old_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b"}]
        new_manifest = MagicMock()
        new_manifest.app_config = [{"instance_name": "a-changed"}, {"instance_name": "b"}]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.get_manifest = Mock(return_value=new_manifest)

        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service.reload_app = AsyncMock()
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._create_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        lifecycle_service.reload_app.assert_not_called()
        lifecycle_service._stop_instance_unlocked.assert_called_once_with("app_a", 0)
        lifecycle_service._create_instance_unlocked.assert_called_once()

    async def test_failure_reloading_one_instance_does_not_block_remaining_instances(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """A 3-instance app where indices 0, 1, and 2 all changed config: if creating the
        replacement for index 0 raises, indices 1 and 2 must still be attempted, and the
        exception must not escape ``apply_changes()`` (see code review finding — per-index
        try/except around the batch reload's create phase in ``_reload_changed_indices``).
        """
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock(), 1: MagicMock(), 2: MagicMock()}})
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
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        created_indices: list[int] = []

        async def create_side_effect(_app_key: str, index: int, _manifest: object, _force_reload: bool = False) -> None:
            created_indices.append(index)
            if index == 0:
                raise RuntimeError("boom")

        lifecycle_service._create_instance_unlocked = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
            side_effect=create_side_effect
        )

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )

        # Must not raise — the failure at index 0 is caught and logged, not propagated.
        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        # All three indices were attempted despite index 0's failure.
        assert created_indices == [0, 1, 2]

    async def test_batch_reload_runs_instances_concurrently_not_sequentially(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Each phase of the batch (stop-all, then create-all — see PR #1687 review finding)
        uses asyncio.gather within itself, not a sequential await-per-index loop (ship-time
        challenge finding — sequential processing held the per-app-key lock for the sum of
        every changed instance's timeout). Proven deterministically for the create phase: index
        1 must reach its create before index 0's create releases, which is only possible if both
        are running concurrently under the same lock acquisition.
        """
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock(), 1: MagicMock()}})
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
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        index_0_entered = asyncio.Event()
        index_0_release = asyncio.Event()
        index_1_entered = asyncio.Event()

        async def create_side_effect(_app_key: str, index: int, _manifest: object, _force_reload: bool = False) -> None:
            if index == 0:
                index_0_entered.set()
                await index_0_release.wait()
            else:
                index_1_entered.set()

        lifecycle_service._create_instance_unlocked = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
            side_effect=create_side_effect
        )

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )
        task = asyncio.create_task(
            lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})
        )

        await asyncio.wait_for(index_0_entered.wait(), timeout=1)
        # If index 1 only starts after index 0 releases, this would deadlock — the whole point
        # of the assertion is that index 1 reaches its create while index 0 is still blocked.
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

    async def test_dormant_app_falls_back_to_full_reload_not_selective(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """A dormant multi-instance app (no running instances) reaching _reload_app_or_changed_instances
        via should_auto_reconcile (autostart just flipped to True) must create ALL instances via a
        full reload_app, not just the ones whose app_config changed. The selective path only creates
        changed indices, permanently leaving unchanged siblings unstarted.
        """
        # Explicitly dormant — no running instances (fixture default is empty, but every other test
        # in this class calls set_registry_apps explicitly, so match the convention).
        set_registry_apps(mock_registry, {})

        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service.reload_app = AsyncMock()
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._create_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"app_a"})
        )

        await lifecycle_service.apply_changes(changes, {"app_a": MagicMock()}, {"app_a": MagicMock()})

        lifecycle_service.reload_app.assert_called_once_with("app_a")
        lifecycle_service._stop_instance_unlocked.assert_not_called()
        lifecycle_service._create_instance_unlocked.assert_not_called()
