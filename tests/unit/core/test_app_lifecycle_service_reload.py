"""Unit tests for AppLifecycleService — change application and reload operations.

Part of the AppLifecycleService unit-test family (``test_app_lifecycle_service*.py``);
shared fixtures live in ``_fixtures_app_lifecycle.py`` via ``conftest.py``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.exceptions import AppBlockedError, AppBootstrapNotReleasedError
from hassette.testing import wait_for
from tests.support.factories import make_change_set

from .conftest import assert_acquires_app_key_lock_once, set_registry_apps


def stub_full_restarts(lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> MagicMock:
    """Stub the whole-app stop/start bodies apply_changes() restarts through; returns the manifest they resolve."""
    manifest = MagicMock()
    mock_registry.get_manifest = Mock(return_value=manifest)
    lifecycle_service._stop_app_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    lifecycle_service._start_app_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    return manifest


class TestApplyChanges:
    async def test_orphans_stop_restarts_restart_and_new_apps_start(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Routes orphans/reimport/reload/new to correct methods when autostart gates pass."""
        manifest = stub_full_restarts(lifecycle_service, mock_registry)
        lifecycle_service.stop_app = AsyncMock()
        lifecycle_service.start_app = AsyncMock()
        # Gates are transparent for autostart=True apps — mock helpers so this test stays
        # focused on routing, not gating (gating is covered by TestApplyChangesGating).
        lifecycle_service.should_autostart = Mock(return_value=True)
        lifecycle_service.should_auto_reconcile = Mock(return_value=True)

        changes = make_change_set(
            orphans={"orphan_app"},
            new_apps={"new_app"},
            reimport_apps={"reimport_app"},
            reload_apps={"reload_app"},
        )

        await lifecycle_service.apply_changes(changes, {}, {})

        lifecycle_service.stop_app.assert_called_once_with("orphan_app")
        lifecycle_service._stop_app_unlocked.assert_any_call("reimport_app")
        lifecycle_service._stop_app_unlocked.assert_any_call("reload_app")
        lifecycle_service._start_app_unlocked.assert_any_call("reimport_app", manifest, True)
        lifecycle_service._start_app_unlocked.assert_any_call("reload_app", manifest, False)
        lifecycle_service.start_app.assert_called_once_with("new_app")

    async def test_blocked_app_raise_does_not_abort_remaining_apps(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Defensive isolation: AppBlockedError from one app_key, whether a new app or a restart, must
        not abort the other apps in the change. This should be structurally unreachable
        (AppChangeDetector.detect_changes() filters every bucket by only_apps before apply_changes()
        ever sees an app_key), but the isolation must hold regardless.
        """

        async def start_app(app_key: str) -> None:
            if app_key == "blocked_app":
                raise AppBlockedError(f"{app_key} blocked")

        async def start_app_unlocked(app_key: str, _manifest: object, _force_reload: bool) -> None:
            if app_key == "blocked_reimport":
                raise AppBlockedError(f"{app_key} blocked")

        stub_full_restarts(lifecycle_service, mock_registry)
        lifecycle_service._start_app_unlocked = AsyncMock(side_effect=start_app_unlocked)  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service.stop_app = AsyncMock()
        lifecycle_service.start_app = AsyncMock(side_effect=start_app)
        lifecycle_service.should_autostart = Mock(return_value=True)
        lifecycle_service.should_auto_reconcile = Mock(return_value=True)

        changes = make_change_set(
            new_apps={"blocked_app", "healthy_app"}, reimport_apps={"blocked_reimport", "reimport_app"}
        )

        await lifecycle_service.apply_changes(changes, {}, {})  # must not raise

        lifecycle_service.start_app.assert_any_call("blocked_app")
        lifecycle_service.start_app.assert_any_call("healthy_app")
        restarted = {c.args[0] for c in lifecycle_service._start_app_unlocked.call_args_list}
        assert restarted == {"blocked_reimport", "reimport_app"}

    async def test_every_restart_stops_before_any_restart_starts(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Owner registries are keyed by instance name, and one change can hand a name from one app to
        another (app_x: a -> b while app_y: b -> a). Every replaced app stops before any replacement
        starts, with each affected app-key lock held across both phases.
        """
        stub_full_restarts(lifecycle_service, mock_registry)
        calls: list[tuple[str, str]] = []

        async def stop(app_key: str) -> None:
            calls.append(("stop", app_key))

        async def start(app_key: str, _manifest: object, _force_reload: bool) -> None:
            assert lifecycle_service._get_app_key_lock("app_x").locked()
            assert lifecycle_service._get_app_key_lock("app_y").locked()
            calls.append(("start", app_key))

        lifecycle_service._stop_app_unlocked = AsyncMock(side_effect=stop)  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._start_app_unlocked = AsyncMock(side_effect=start)  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service.should_auto_reconcile = Mock(return_value=True)

        changes = make_change_set(reload_apps={"app_x", "app_y"})

        await lifecycle_service.apply_changes(changes, {}, {})

        assert [phase for phase, _ in calls] == ["stop", "stop", "start", "start"]
        assert {key for _, key in calls} == {"app_x", "app_y"}
        assert not lifecycle_service._get_app_key_lock("app_x").locked()
        assert not lifecycle_service._get_app_key_lock("app_y").locked()

    async def test_selective_restarts_stop_every_app_before_creating_any(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """The same ordering holds for per-instance restarts: app_x's instance renames a -> b while
        app_y's renames b -> c, so app_y's old b must be gone before app_x's new b is created.
        """
        set_registry_apps(mock_registry, {"app_x": {0: MagicMock()}, "app_y": {0: MagicMock()}})
        old = {
            "app_x": MagicMock(app_config=[{"instance_name": "a"}]),
            "app_y": MagicMock(app_config=[{"instance_name": "b"}]),
        }
        new = {
            "app_x": MagicMock(app_config=[{"instance_name": "b"}]),
            "app_y": MagicMock(app_config=[{"instance_name": "c"}]),
        }
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.get_manifest = Mock(side_effect=new.get)
        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        calls: list[tuple[str, str]] = []

        async def stop(app_key: str, _index: int) -> None:
            calls.append(("stop", app_key))

        async def create(app_key: str, _index: int, _manifest: object, _force_reload: bool = False) -> None:
            calls.append(("create", app_key))

        lifecycle_service._stop_instance_unlocked = AsyncMock(side_effect=stop)  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._create_instance_unlocked = AsyncMock(side_effect=create)  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service.apply_changes(make_change_set(reload_apps={"app_x", "app_y"}), old, new)

        assert [phase for phase, _ in calls] == ["stop", "stop", "create", "create"]
        assert {key for _, key in calls} == {"app_x", "app_y"}

    async def test_failed_restart_does_not_abort_the_others(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """A replacement that fails to start is logged, and the rest of the batch still starts."""
        stub_full_restarts(lifecycle_service, mock_registry)

        async def start(app_key: str, _manifest: object, _force_reload: bool) -> None:
            if app_key == "app_x":
                raise RuntimeError("boom")

        lifecycle_service._start_app_unlocked = AsyncMock(side_effect=start)  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service.should_auto_reconcile = Mock(return_value=True)

        await lifecycle_service.apply_changes(make_change_set(reload_apps={"app_x", "app_y"}), {}, {})  # must not raise

        assert {c.args[0] for c in lifecycle_service._start_app_unlocked.call_args_list} == {"app_x", "app_y"}
        assert not lifecycle_service._get_app_key_lock("app_x").locked()


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

    async def test_stops_but_does_not_restart_blocked_app(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """A manual reload_app() for an app excluded by the --app filter stops the existing
        instances but must not recreate them — regression test for the P1 finding on PR #1873
        that also applies to reload, since reload is stop-then-start.

        Re-raises AppBlockedError after the stop completes (P2 follow-up finding on the same
        PR) rather than silently swallowing it — the stop side-effect is real and worth
        keeping, but the caller must still see that the restart was refused.
        """
        mock_registry.unregister_app = Mock(return_value=None)
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})
        mock_registry.is_blocked = Mock(return_value=True)

        with pytest.raises(AppBlockedError):
            await lifecycle_service.reload_app("test_app")

        mock_registry.unregister_app.assert_called_once_with("test_app")
        mock_factory.create_instances.assert_not_called()


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
        non-reentrant asyncio.Lock — the helper's asyncio.wait_for turns that hang into a
        test failure instead of a stuck test run.
        """
        mock_registry.unregister_app = Mock(return_value=None)
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_running_apps = Mock(return_value={})

        await assert_acquires_app_key_lock_once(
            lifecycle_service, "test_app", lambda: lifecycle_service.reload_app("test_app")
        )

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
    """Per-instance selective restart in apply_changes()'s reload_apps handling."""

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

        changes = make_change_set(reload_apps={"app_a"})

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        # Only index 1 was ever unregistered/stopped — index 0 is never touched.
        mock_registry.unregister_app.assert_called_once_with("app_a", 1)
        lifecycle_service.shutdown_instance.assert_called_once_with(app1, 1, deadline=None)

        # Only index 1 was ever (re)created.
        mock_factory.create_single_instance.assert_called_once()
        # create_single_instance(app_key, manifest, index, config_dict, app_class) — index is arg[2]
        assert mock_factory.create_single_instance.call_args.args[2] == 1

    async def test_reimport_restarts_all_instances_not_changed_ones(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """A file-level change (reimport_apps bucket) restarts the whole app key with a fresh class
        import, never the per-instance path — regardless of any per-instance config diff.
        """
        manifest = stub_full_restarts(lifecycle_service, mock_registry)
        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = make_change_set(reimport_apps={"app_a"})

        # original/current configs are irrelevant to the reimport_apps branch — it always does
        # a full reload, so pass configs that (if they leaked into the reload_apps branch) would
        # show a per-instance diff, proving reimport truly bypasses that path.
        old_manifest = MagicMock(app_config=[{"instance_name": "a"}])
        new_manifest = MagicMock(app_config=[{"instance_name": "a_changed"}])

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        lifecycle_service._stop_app_unlocked.assert_called_once_with("app_a")
        lifecycle_service._start_app_unlocked.assert_called_once_with("app_a", manifest, True)
        lifecycle_service._stop_instance_unlocked.assert_not_called()

    async def test_instance_count_change_falls_back_to_full_restart(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """When the instance list length changes between old and new config, the
        system falls back to restarting every instance instead of per-instance reload.
        """
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock()}})
        old_manifest = MagicMock()
        old_manifest.app_config = [{"instance_name": "a"}]
        new_manifest = MagicMock()
        new_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b"}]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        stub_full_restarts(lifecycle_service, mock_registry)
        mock_registry.get_manifest = Mock(return_value=new_manifest)

        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = make_change_set(reload_apps={"app_a"})

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        lifecycle_service._stop_app_unlocked.assert_called_once_with("app_a")
        lifecycle_service._start_app_unlocked.assert_called_once_with("app_a", new_manifest, False)
        lifecycle_service._stop_instance_unlocked.assert_not_called()

    async def test_renamed_index_takes_selective_reload_path(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Renaming one instance restarts only that index, not the whole app."""
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock(), 1: MagicMock()}})
        old_manifest = MagicMock()
        old_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b"}]
        new_manifest = MagicMock()
        new_manifest.app_config = [{"instance_name": "a_changed"}, {"instance_name": "b"}]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        stub_full_restarts(lifecycle_service, mock_registry)
        mock_registry.get_manifest = Mock(return_value=new_manifest)

        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._create_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = make_change_set(reload_apps={"app_a"})

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        lifecycle_service._stop_app_unlocked.assert_not_called()
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
        exception must not escape ``apply_changes()`` (the per-index try/except around the
        create phase).
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

        changes = make_change_set(reload_apps={"app_a"})

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
        """Each phase of the batch (stop-all, then create-all) uses asyncio.gather within itself,
        not a sequential await-per-index loop, which would hold the per-app-key lock for the sum of
        every changed instance's timeout. Proven deterministically for the create phase: index 1
        must reach its create before index 0's create releases, which is only possible if both are
        running concurrently under the same lock acquisition.
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

        changes = make_change_set(reload_apps={"app_a"})
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

    async def test_autostart_false_app_is_not_restarted_on_config_change(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """A config edit to one instance of a currently-dormant autostart=false app must not
        start any instance — should_auto_reconcile gates the whole per-instance branch, not just
        individual instance restarts.
        """
        old_manifest = MagicMock()
        old_manifest.app_config = [{"instance_name": "a"}]
        new_manifest = MagicMock()
        new_manifest.app_config = [{"instance_name": "a_changed"}]

        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        stub_full_restarts(lifecycle_service, mock_registry)
        mock_registry.get_manifest = Mock(return_value=new_manifest)

        lifecycle_service.should_auto_reconcile = Mock(return_value=False)
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = make_change_set(reload_apps={"app_a"})

        await lifecycle_service.apply_changes(changes, {"app_a": old_manifest}, {"app_a": new_manifest})

        lifecycle_service._stop_app_unlocked.assert_not_called()
        lifecycle_service._start_app_unlocked.assert_not_called()
        lifecycle_service._stop_instance_unlocked.assert_not_called()

    async def test_dormant_app_falls_back_to_full_reload_not_selective(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """A dormant multi-instance app (no running instances) reaching apply_changes() via
        should_auto_reconcile (autostart just flipped to True) must create ALL instances via a full
        restart, not just the ones whose app_config changed. The selective path only creates
        changed indices, permanently leaving unchanged siblings unstarted.
        """
        # Explicitly dormant — no running instances (fixture default is empty, but every other test
        # in this class calls set_registry_apps explicitly, so match the convention).
        set_registry_apps(mock_registry, {})

        manifest = stub_full_restarts(lifecycle_service, mock_registry)
        lifecycle_service.should_auto_reconcile = Mock(return_value=True)
        lifecycle_service._stop_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        lifecycle_service._create_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        changes = make_change_set(reload_apps={"app_a"})

        await lifecycle_service.apply_changes(changes, {"app_a": MagicMock()}, {"app_a": MagicMock()})

        lifecycle_service._stop_app_unlocked.assert_called_once_with("app_a")
        lifecycle_service._start_app_unlocked.assert_called_once_with("app_a", manifest, False)
        lifecycle_service._stop_instance_unlocked.assert_not_called()
        lifecycle_service._create_instance_unlocked.assert_not_called()
