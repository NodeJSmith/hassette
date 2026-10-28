"""Unit tests for AppLifecycleService — per-instance start, stop, reload, and locking.

Part of the AppLifecycleService unit-test family (``test_app_lifecycle_service*.py``);
shared fixtures live in ``_fixtures_app_lifecycle.py`` via ``conftest.py``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from hassette_wire import ResourceStatus

from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.exceptions import AppBlockedError
from hassette.testing import EventCapture, wait_for
from tests.support.web_manifest_helpers import make_app_instance_info

from .conftest import app_state_payloads, assert_acquires_app_key_lock_once, make_mock_app_instance


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

        failure_info = make_app_instance_info(
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

        failed_payloads = app_state_payloads(event_capture, ResourceStatus.FAILED)
        assert len(failed_payloads) == 1
        payload = failed_payloads[0]
        assert payload.app_key == "app_a"
        assert payload.index == 1
        assert payload.instance_name == "inst_1"


class TestStopInstanceFailure:
    async def test_registry_lookup_failure_does_not_raise(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """An exception from the registry lookup is caught and logged, not propagated.

        Mirrors TestStopAppFailure (test_app_lifecycle_service_coverage.py) but for the
        per-instance path — proves _stop_instance_unlocked's try/except containment works.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get = Mock(side_effect=RuntimeError("registry corrupted"))
        lifecycle_service.shutdown_instances = AsyncMock()

        await lifecycle_service.stop_instance("test_app", 0)  # must not raise

        lifecycle_service.shutdown_instances.assert_not_called()


class TestStopInstanceBehavior:
    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_stops_running_instance_at_target_index(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """stop_instance shuts down the running instance at the target index only, leaving its
        unregistration to shutdown_instance (after the teardown).
        """
        mock_manifest.app_config = [{"instance_name": "a"}, {"instance_name": "b"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_failed_instance_infos = Mock(return_value={})
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        app1 = MagicMock()
        mock_registry.get = Mock(side_effect=lambda _key, index=0: app1 if index == 1 else None)
        lifecycle_service.shutdown_instances = AsyncMock()

        await lifecycle_service.stop_instance("test_app", 1)

        mock_registry.unregister_app.assert_not_called()
        lifecycle_service.shutdown_instances.assert_called_once_with({1: app1})

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_out_of_range_index_skips_cleanly(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """stop_instance no-ops for an untracked index beyond the current manifest's count."""
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_instances = Mock(return_value={0: MagicMock()})
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.unregister_app = Mock()

        await lifecycle_service.stop_instance("test_app", 5)

        mock_registry.unregister_app.assert_not_called()

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_tracked_out_of_range_index_is_still_stopped(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """An instance orphaned by a config shrink (still tracked, index now out of range) stays
        stoppable — prune_stale_failed_indices only prunes stale *failed* entries, so refusing
        here would leave it running with no way to shut it down.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_instances = Mock(return_value={0: MagicMock(), 2: MagicMock()})
        mock_registry.get_failed_instance_infos = Mock(return_value={})
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        orphan = MagicMock()
        mock_registry.get = Mock(side_effect=lambda _key, index=0: orphan if index == 2 else None)
        lifecycle_service.shutdown_instances = AsyncMock()

        await lifecycle_service.stop_instance("test_app", 2)

        lifecycle_service.shutdown_instances.assert_called_once_with({2: orphan})

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_succeeds_without_admission_check_before_bootstrap_release(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
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
    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_create_instance_failure_does_not_raise(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
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
    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_creates_and_initializes_target_index(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
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

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_out_of_range_index_skips_cleanly(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """start_instance no-ops for an index beyond the current manifest's instance count."""
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)

        await lifecycle_service.start_instance("test_app", 5)

        mock_factory.create_single_instance.assert_not_called()

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_negative_index_skips_cleanly(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """start_instance no-ops for a negative index rather than resolving it via Python's
        negative-indexing semantics into the last configured instance (ship-time challenge
        finding — the shared _instance_index_in_range() helper only checked the upper bound).
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)

        await lifecycle_service.start_instance("test_app", -1)

        mock_factory.create_single_instance.assert_not_called()

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_blocked_app_skips_without_creating(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """A manual start_instance() for an app excluded by the --app filter must not bypass
        that exclusion — regression test for the P1 finding on PR #1873:
        build_manifest_info() now gives a blocked app's not-yet-tracked configured indices a
        synthetic STOPPED status, which makes the web UI's per-instance Start button (and the
        CLI's ``app start --instance``) visible for an app the filter excluded. Nothing else in
        start_instance()/_create_instance_unlocked() checks blocked state, so this guard is the
        only thing that stops the bypass.

        Raises AppBlockedError rather than silently no-op'ing (P2 follow-up finding on the
        same PR) — a plain no-op would let the web route respond 202 "accepted" for a request
        nothing acted on.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.is_blocked = Mock(return_value=True)

        with pytest.raises(AppBlockedError):
            await lifecycle_service.start_instance("test_app", 0)

        mock_factory.create_single_instance.assert_not_called()
        mock_registry.is_blocked.assert_called_with("test_app")


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

        lifecycle_service._reload_instance_unlocked = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await assert_acquires_app_key_lock_once(
            lifecycle_service, "test_app", lambda: lifecycle_service.reload_instance("test_app", 0)
        )

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

        await assert_acquires_app_key_lock_once(
            lifecycle_service, "test_app", lambda: lifecycle_service.stop_instance("test_app", 0)
        )

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_start_instance_acquires_app_key_lock_once(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """start_instance acquires the per-app-key lock exactly once."""
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=None)
        mock_factory.get_load_error = Mock(return_value=ValueError("boom"))
        mock_registry.get_failed_instance_infos = Mock(return_value={})

        await assert_acquires_app_key_lock_once(
            lifecycle_service, "test_app", lambda: lifecycle_service.start_instance("test_app", 0)
        )

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
        _create_instance_unlocked must notice that nothing was registered, emit the
        recorded failure, and return early rather than proceeding to initialize_instances().
        """
        event_capture.install(mock_hassette)
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())

        failure_info = make_app_instance_info(
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

        failed_payloads = app_state_payloads(event_capture, ResourceStatus.FAILED)
        assert len(failed_payloads) == 1


class TestCreateInstanceUnlockedPostRegistrationFailure:
    async def test_never_started_phantom_is_shut_down_with_its_own_hooks_skipped(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """If send_event raises after create_single_instance registered the app but before its
        initialization started, the phantom is shut down with the exception as its cause and its
        own shutdown hooks skipped — an app that never initialized must not run ``on_shutdown``.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())

        mock_inst = make_mock_app_instance()
        mock_registry.get = Mock(return_value=mock_inst)

        failure = RuntimeError("event bus failure")
        mock_hassette.send_event = AsyncMock(side_effect=failure)
        lifecycle_service.shutdown_instance = AsyncMock()

        with pytest.raises(RuntimeError, match="event bus failure"):
            await lifecycle_service._create_instance_unlocked("test_app", 0, mock_manifest)

        lifecycle_service.shutdown_instance.assert_awaited_once_with(mock_inst, 0, cause=failure)
        assert mock_inst._skip_own_shutdown_hooks is True

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_initialized_phantom_is_shut_down_with_its_own_hooks(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """An app that initialized before something after it raised (reconciliation) gets its
        ``on_shutdown``: the phantom is shut down with the cause, without the hook skip.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())

        mock_inst = make_mock_app_instance()
        mock_registry.get = Mock(return_value=mock_inst)

        failure = RuntimeError("reconcile failed")
        lifecycle_service.initialize_instances = AsyncMock(side_effect=failure)
        lifecycle_service.shutdown_instance = AsyncMock()

        with pytest.raises(RuntimeError, match="reconcile failed"):
            await lifecycle_service._create_instance_unlocked("test_app", 0, mock_manifest)

        lifecycle_service.shutdown_instance.assert_awaited_once_with(mock_inst, 0, cause=failure)
        assert mock_inst._skip_own_shutdown_hooks is False

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_phantom_already_gone_records_a_post_registration_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """When nothing is registered at the index any more, there is nothing to shut down; the
        failure is recorded so the index doesn't silently look stopped.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())

        mock_inst = make_mock_app_instance()
        lookups = iter([mock_inst])
        mock_registry.get = Mock(side_effect=lambda _key, _index=0: next(lookups, None))
        lifecycle_service.initialize_instances = AsyncMock(side_effect=RuntimeError("reconcile failed"))
        lifecycle_service.shutdown_instance = AsyncMock()

        with pytest.raises(RuntimeError, match="reconcile failed"):
            await lifecycle_service._create_instance_unlocked("test_app", 0, mock_manifest)

        lifecycle_service.shutdown_instance.assert_not_called()
        mock_registry.record_failure.assert_called_once()
        assert mock_registry.record_failure.call_args.args[:2] == ("test_app", 0)


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

    async def test_blocked_app_stops_but_does_not_recreate(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """A manual reload_instance() for an app excluded by the --app filter stops the
        existing instance but must not recreate it — reload is stop-then-create, and the
        guard lives in the shared ``_create_instance_unlocked`` create step (see
        TestStartInstanceBehavior.test_blocked_app_skips_without_creating for the start-side
        regression test for the same P1 finding on PR #1873).

        ``_create_instance_unlocked`` raises AppBlockedError (P2 follow-up finding on the same
        PR) — called here directly (not through ``reload_instance()``), so the exception
        propagates straight out rather than being caught and re-raised by a wrapper.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_registry.is_blocked = Mock(return_value=True)
        mock_registry.get_failed_instance_infos = Mock(return_value={})
        mock_registry.unregister_app = Mock(return_value=None)

        with pytest.raises(AppBlockedError):
            await lifecycle_service._reload_instance_unlocked("test_app", 0)

        mock_factory.create_single_instance.assert_not_called()


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

    async def test_reload_instance_reraises_blocked_error(
        self,
        lifecycle_service: AppLifecycleService,
    ) -> None:
        """Unlike other failures (see the test above), AppBlockedError from
        _reload_instance_unlocked must propagate out of the public reload_instance() rather
        than being swallowed — P2 follow-up finding on PR #1873: a swallowed rejection would
        let the web route respond 202 "accepted" for a restart that was actually refused.
        """
        lifecycle_service._reload_instance_unlocked = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
            side_effect=AppBlockedError("App 'test_app' is blocked by the --app filter")
        )

        with pytest.raises(AppBlockedError):
            await lifecycle_service.reload_instance("test_app", 0)


class TestStopInstanceUnlockedShutdownFailure:
    async def test_shutdown_instances_failure_does_not_raise(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """An exception raised by shutdown_instances() (as opposed to the registry lookup, already
        covered by TestStopInstanceFailure.test_registry_lookup_failure_does_not_raise) is also
        caught and logged by the same try/except in _stop_instance_unlocked.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_failed_instance_infos = Mock(return_value={})
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        app1 = MagicMock()
        mock_registry.get = Mock(return_value=app1)
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
