"""Unit tests filling coverage gaps in AppLifecycleService.

Complements test_app_lifecycle_service.py (init/properties/initialize/shutdown/bootstrap/
apply-changes gating) and test_app_lifecycle_service_operations.py (start/stop/reload/
resolve_only_app/refresh_config/reconcile). This file targets the remaining branches:
specific factory exceptions, stop/reload failure paths, start_apps error aggregation,
handle_change_event's unblock-and-no-op branches, resolve_only_app's error/prod/multi-only
paths, and reconcile_app_registrations' degraded-mode fallbacks.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, seal

import pytest

from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.exceptions import InvalidInheritanceError, UndefinedUserConfigError
from hassette.types import Topic


class TestBootstrapAppsSuccessLogging:
    async def test_emits_load_completed_when_apps_running(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock, mock_hassette: MagicMock
    ) -> None:
        """The successful-initialization branch (running_count > 0) still emits APP_LOAD_COMPLETED."""
        mock_registry.manifests = {"app_a": MagicMock()}
        mock_registry.active_manifests = {}
        mock_registry.get_snapshot = Mock(return_value=MagicMock(running_count=1, failed_count=0))

        await lifecycle_service.bootstrap_apps()

        calls = mock_hassette.send_event.call_args_list
        completed_calls = [call for call in calls if call[0][0].topic == Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED]
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
        lifecycle_service.shutdown_instances = (
            AsyncMock()
        )  # branch-isolation: skip shutdown to test unregister error path

        await lifecycle_service.stop_app("test_app")

        lifecycle_service.shutdown_instances.assert_not_called()


class TestReloadAppFailure:
    async def test_stop_failure_prevents_start_and_does_not_raise(self, lifecycle_service: AppLifecycleService) -> None:
        """If stop_app raises, reload_app catches it and never calls start_app."""
        # branch-isolation: stop_app forced to raise for reload_app error path
        lifecycle_service.stop_app = AsyncMock(side_effect=RuntimeError("stop blew up"))
        lifecycle_service.start_app = AsyncMock()  # branch-isolation: verify start_app is never reached

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

        async def fake_start_app(app_key: str) -> None:
            if app_key == "app_a":
                raise RuntimeError("app_a exploded")
            started.append(app_key)

        lifecycle_service.start_app = fake_start_app  # pyright: ignore[reportAttributeAccessIssue]

        # Should not raise despite app_a's failure.
        await lifecycle_service.start_apps()

        assert started == ["app_b"]


class TestHandleChangeEventBranches:
    async def test_no_changes_returns_without_applying_or_emitting(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock, mock_hassette: MagicMock
    ) -> None:
        """When detect_changes reports no changes, apply_changes is skipped and no event fires."""
        lifecycle_service.change_detector.detect_changes = Mock(  # pyright: ignore[reportAttributeAccessIssue]
            return_value=ChangeSet(
                orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset()
            )
        )
        lifecycle_service.apply_changes = (
            AsyncMock()
        )  # branch-isolation: verify apply_changes is skipped on empty changeset

        await lifecycle_service.handle_change_event()

        lifecycle_service.apply_changes.assert_not_called()
        completed_calls = [
            call
            for call in mock_hassette.send_event.call_args_list
            if call[0][0].topic == Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED
        ]
        assert len(completed_calls) == 0

    async def test_unblocked_apps_are_folded_into_new_apps(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock, mock_hassette: MagicMock
    ) -> None:
        """Apps unblocked by reconcile_blocked_apps (and not already running/changing) are started."""
        lifecycle_service.change_detector.detect_changes = Mock(  # pyright: ignore[reportAttributeAccessIssue]
            return_value=ChangeSet(
                orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset()
            )
        )
        # branch-isolation: reconcile_blocked_apps forced to return unblocked apps
        lifecycle_service.reconcile_blocked_apps = Mock(return_value={"unblocked_app"})
        mock_registry.apps = {}

        applied: list[ChangeSet] = []

        async def capture_apply(changes: ChangeSet) -> None:
            applied.append(changes)

        lifecycle_service.apply_changes = capture_apply  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service.handle_change_event()

        assert len(applied) == 1
        assert applied[0].new_apps == frozenset({"unblocked_app"})

        completed_calls = [
            call
            for call in mock_hassette.send_event.call_args_list
            if call[0][0].topic == Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED
        ]
        assert len(completed_calls) == 1


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


class TestResolveOnlyAppErrorAndEdgeCases:
    async def test_bad_config_app_is_skipped_and_logged(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """An app whose only-decorator check raises UndefinedUserConfigError is skipped, not fatal."""
        mock_registry.active_manifests = {"test_app": mock_manifest}
        mock_factory.check_only_app_decorator = Mock(side_effect=UndefinedUserConfigError("bad config"))

        await lifecycle_service.resolve_only_app()

        mock_registry.set_only_app.assert_called_with(None)

    async def test_allowed_in_prod_when_explicitly_enabled(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """only_app decorator is honored in prod mode when allow_only_app_in_prod=True."""
        mock_hassette.config.dev_mode = False
        mock_hassette.config.allow_only_app_in_prod = True
        mock_registry.active_manifests = {"test_app": mock_manifest}
        mock_factory.check_only_app_decorator = Mock(return_value=True)

        await lifecycle_service.resolve_only_app()

        mock_registry.set_only_app.assert_called_with("test_app")

    async def test_multiple_only_apps_raises(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Two apps both marked @only raises RuntimeError naming both."""
        manifest_a = MagicMock()
        manifest_a.app_key = "app_a"
        manifest_a.full_path = None
        manifest_b = MagicMock()
        manifest_b.app_key = "app_b"
        manifest_b.full_path = None
        mock_registry.active_manifests = {"app_a": manifest_a, "app_b": manifest_b}
        mock_factory.check_only_app_decorator = Mock(return_value=True)

        with pytest.raises(RuntimeError, match="Multiple apps marked as only"):
            await lifecycle_service.resolve_only_app()

    async def test_force_reload_passed_for_changed_files(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """A manifest whose full_path is in changed_file_paths triggers force_reload=True."""
        mock_registry.active_manifests = {"test_app": mock_manifest}
        calls: list[bool] = []

        def capture_force_reload(_manifest: MagicMock, *, force_reload: bool) -> bool:
            calls.append(force_reload)
            return False

        mock_factory.check_only_app_decorator = Mock(side_effect=capture_force_reload)

        await lifecycle_service.resolve_only_app(changed_file_paths=frozenset({mock_manifest.full_path}))

        assert calls == [True]


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
