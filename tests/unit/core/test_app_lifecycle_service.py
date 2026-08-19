"""Unit tests for AppLifecycleService.

Complements test_app_lifecycle_service_coverage.py, test_app_lifecycle_service_instances.py
(initialize/cleanup/shutdown instance operations split out of this file), and
test_app_lifecycle_service_operations.py.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.bus import Bus
from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppAdmissionMode, AppLifecycleService
from hassette.test_utils import EventCapture
from hassette.types import Topic

from .conftest import set_registry_apps


class TestAppLifecycleServiceInit:
    def test_stores_registry_reference(
        self, mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """Verify constructor stores the registry reference."""
        with (
            patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
            patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
        ):
            service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
        assert service.registry is mock_registry

    def test_creates_factory_internally(self, mock_hassette: MagicMock, mock_registry: MagicMock) -> None:
        """Verify constructor creates an AppFactory."""
        with (
            patch("hassette.core.app_lifecycle_service.AppFactory") as factory_cls,
            patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
        ):
            service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
            factory_cls.assert_called_once_with(mock_hassette, mock_registry)
            assert service.factory is factory_cls.return_value

    def test_creates_change_detector_internally(
        self, mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """Verify constructor creates an AppChangeDetector."""
        with (
            patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
            patch("hassette.core.app_lifecycle_service.AppChangeDetector") as detector_cls,
        ):
            service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
            detector_cls.assert_called_once()
            assert service.change_detector is detector_cls.return_value

    def test_does_not_create_bus_child(
        self, mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """Verify constructor does not create a Bus child (file-watcher subscription belongs to AppHandler.bus)."""
        with (
            patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
            patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
        ):
            service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)

        assert not any(isinstance(child, Bus) for child in service.children)


class TestOnlyAppRegistryAgreement:
    """Pin: registry.only_apps must equal the value passed to detect_changes."""

    async def test_detect_changes_receives_registry_only_apps(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """The value passed as only_apps to detect_changes matches registry.only_apps at call time."""
        mock_registry.only_apps = frozenset({"pinned_app"})

        captured_only_apps: list[frozenset[str] | None] = []

        def capture_only_apps(_original, _current, _changed_paths, *, only_apps=None):
            captured_only_apps.append(only_apps)
            return ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset(),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )

        lifecycle_service.change_detector.detect_changes = capture_only_apps  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service.handle_change_event()

        assert len(captured_only_apps) == 1
        assert captured_only_apps[0] == mock_registry.only_apps


class TestBootstrapAppsAdmission:
    async def test_bootstrap_uses_wait_for_release_mode(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        mock_registry.manifests = {"app_a": MagicMock()}
        mock_registry.get_snapshot = Mock(return_value=MagicMock(running_count=0, failed_count=0))
        lifecycle_service.start_apps = AsyncMock()

        await lifecycle_service.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

        mock_hassette.app_bootstrap_coordinator.wait_released.assert_not_awaited()
        lifecycle_service.start_apps.assert_awaited_once_with(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

    async def test_bootstrap_replays_deferred_reconciliation_after_startup(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        manifest = MagicMock()
        original_manifest = MagicMock()
        mock_registry.manifests = {"app_a": manifest}
        mock_registry.enabled_manifests = {"app_a": manifest}
        mock_registry.get_snapshot = Mock(return_value=MagicMock(running_count=0, failed_count=0))
        lifecycle_service.start_apps = AsyncMock()
        lifecycle_service.resolve_only_apps = AsyncMock()
        lifecycle_service.change_detector.detect_changes = Mock(
            return_value=ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset({"app_a"}),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )
        )
        lifecycle_service.apply_changes = AsyncMock()
        lifecycle_service._record_pre_release_reconciliation(
            original_apps_config={"old_app": original_manifest},
            current_apps_config={"app_a": manifest},
            changed_file_paths=frozenset(),
        )

        await lifecycle_service.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

        lifecycle_service.start_apps.assert_awaited_once_with(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)
        lifecycle_service.apply_changes.assert_awaited_once()
        assert lifecycle_service._pending_reconciliation is None

    async def test_bootstrap_replays_deferred_reconciliation_when_no_manifests(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """The empty-manifest early return must still await release and replay a queued
        pre-release reconciliation rather than silently dropping it.

        `registry.manifests == {}` short-circuits bootstrap_apps() before start_apps() and
        the unconditional `_replay_pre_release_reconciliation_if_needed()` call that follows
        it, so that replay must happen on this early-return path too.
        """
        mock_registry.manifests = {}
        lifecycle_service.resolve_only_apps = AsyncMock()
        lifecycle_service.change_detector.detect_changes = Mock(
            return_value=ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset({"app_a"}),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )
        )
        lifecycle_service.apply_changes = AsyncMock()
        lifecycle_service._record_pre_release_reconciliation(
            original_apps_config={"old_app": MagicMock()},
            current_apps_config={"app_a": MagicMock()},
            changed_file_paths=frozenset(),
        )

        await lifecycle_service.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

        mock_hassette.app_bootstrap_coordinator.wait_released.assert_awaited_once()
        lifecycle_service.apply_changes.assert_awaited_once()
        assert lifecycle_service._pending_reconciliation is None


class TestAppLifecycleServiceProperties:
    def test_startup_timeout_from_config(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock
    ) -> None:
        """Returns hassette.config.lifecycle.app_startup_timeout_seconds."""
        assert lifecycle_service.startup_timeout == mock_hassette.config.lifecycle.app_startup_timeout_seconds

    def test_shutdown_timeout_from_config(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock
    ) -> None:
        """Returns hassette.config.lifecycle.app_shutdown_timeout_seconds."""
        assert lifecycle_service.shutdown_timeout == mock_hassette.config.lifecycle.app_shutdown_timeout_seconds


class TestBootstrapApps:
    async def test_skips_when_no_manifests(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock, mock_hassette: MagicMock
    ) -> None:
        """Returns early when no manifests are configured."""
        mock_registry.manifests = {}

        await lifecycle_service.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

        mock_hassette.send_event.assert_not_called()

    async def test_emits_load_completed_event(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Emits APP_LOAD_COMPLETED after starting apps."""
        event_capture.install(mock_hassette)
        mock_registry.manifests = {"app_a": MagicMock()}
        mock_registry.active_manifests = {}
        mock_registry.get_snapshot = Mock(return_value=MagicMock(running_count=0, failed_count=0))

        await lifecycle_service.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

        completed_calls = event_capture.by_topic(Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED)
        assert len(completed_calls) == 1

    async def test_handles_crash(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls handle_crash and re-raises on exception."""
        mock_registry.manifests = {"app_a": MagicMock()}
        lifecycle_service.resolve_only_apps = AsyncMock(side_effect=RuntimeError("crash"))

        with patch("hassette.core.app_lifecycle_service.handle_crash") as mock_handle_crash:
            with pytest.raises(RuntimeError, match="crash"):
                await lifecycle_service.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

            mock_handle_crash.assert_called_once()
            assert mock_handle_crash.call_args[0][0] is lifecycle_service
            assert isinstance(mock_handle_crash.call_args[0][1], RuntimeError)


class TestStartApps:
    async def test_gathers_all_app_starts(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Starts only autostart_manifests apps (not all active_manifests) by default."""
        manifest_a = MagicMock()
        manifest_b = MagicMock()
        mock_registry.autostart_manifests = {"app_a": manifest_a, "app_b": manifest_b}
        mock_registry.get_manifest = Mock(side_effect=lambda k: {"app_a": manifest_a, "app_b": manifest_b}.get(k))
        mock_registry.get_running_apps = Mock(return_value={})

        await lifecycle_service.start_apps()

        assert mock_factory.create_instances.call_count == 2

    async def test_excludes_autostart_false_apps_by_default(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Apps not in autostart_manifests are not started when no explicit set is passed."""
        manifest_a = MagicMock()
        # autostart_manifests only contains app_a; active_manifests also has app_b (autostart=false)
        mock_registry.autostart_manifests = {"app_a": manifest_a}
        mock_registry.get_manifest = Mock(side_effect=lambda k: {"app_a": manifest_a}.get(k))
        mock_registry.get_running_apps = Mock(return_value={})

        await lifecycle_service.start_apps()

        assert mock_factory.create_instances.call_count == 1

    async def test_cancelled_error_is_not_swallowed(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
    ) -> None:
        """A CancelledError from one gathered start_app() call must propagate, not be dropped.

        asyncio.CancelledError is a BaseException, not an Exception, so the
        `isinstance(r, Exception)` filter silently drops it from asyncio.gather's
        return_exceptions=True results. Swallowing it here means bootstrap_apps() proceeds
        as if startup completed normally after a cancellation mid-flight.
        """
        mock_registry.autostart_manifests = {"app_a": MagicMock(), "app_b": MagicMock()}

        async def maybe_cancel(app_key: str, **_kwargs: object) -> None:
            if app_key == "app_a":
                raise asyncio.CancelledError()

        lifecycle_service.start_app = AsyncMock(side_effect=maybe_cancel)

        with pytest.raises(asyncio.CancelledError):
            await lifecycle_service.start_apps()


class TestShouldAutostart:
    @pytest.mark.parametrize(
        ("autostart", "manifest_exists", "expected"),
        [
            (True, True, True),
            (False, True, False),
            (None, False, False),
        ],
        ids=["autostart_true", "autostart_false", "manifest_missing"],
    )
    def test_should_autostart(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        autostart: bool | None,
        manifest_exists: bool,
        expected: bool,
    ) -> None:
        if manifest_exists:
            manifest = MagicMock()
            manifest.autostart = autostart
            mock_registry.get_manifest = Mock(return_value=manifest)
        else:
            mock_registry.get_manifest = Mock(return_value=None)

        assert lifecycle_service.should_autostart("app_a") is expected


class TestShouldAutoReconcile:
    @pytest.mark.parametrize(
        ("autostart", "is_running", "expected"),
        [
            (False, True, True),
            (True, False, True),
            (False, False, False),
        ],
        ids=["running_overrides_autostart", "autostart_true", "not_running_no_autostart"],
    )
    def test_should_auto_reconcile(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        autostart: bool,
        is_running: bool,
        expected: bool,
    ) -> None:
        manifest = MagicMock()
        manifest.autostart = autostart
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock()}} if is_running else {})

        assert lifecycle_service.should_auto_reconcile("app_a") is expected


class TestStopAppLocking:
    async def test_stop_app_holds_app_key_lock_during_unregister(
        self,
        lifecycle_service: AppLifecycleService,
    ) -> None:
        """stop_app acquires the per-app-key lock before calling the unlocked body, and
        releases it afterward — stop_app must hold the lock while it unregisters and shuts
        down instances.
        """
        lock = lifecycle_service._get_app_key_lock("test_app")
        lock_held_during_call = False

        async def fake_unlocked(_app_key: str) -> None:
            nonlocal lock_held_during_call
            lock_held_during_call = lock.locked()

        lifecycle_service._stop_app_unlocked = AsyncMock(side_effect=fake_unlocked)

        await lifecycle_service.stop_app("test_app")

        assert lock_held_during_call is True
        assert not lock.locked()


class TestApplyChangesGating:
    async def test_new_apps_autostart_false_not_started(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """new_apps with autostart=False are skipped in apply_changes."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {})
        lifecycle_service.start_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset({"app_a"}),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.start_app.assert_not_called()

    async def test_new_apps_autostart_true_are_started(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """new_apps with autostart=True are started in apply_changes."""
        manifest = MagicMock()
        manifest.autostart = True
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {})
        lifecycle_service.start_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset({"app_a"}),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.start_app.assert_called_once_with("app_a")

    async def test_reload_apps_running_autostart_false_are_reloaded(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """reload_apps for a running app are always reconciled (autostart=False, but running)."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock()}})
        lifecycle_service.reload_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset({"app_a"}),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.reload_app.assert_called_once_with("app_a")

    async def test_reload_apps_not_running_autostart_false_are_skipped(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """reload_apps for a non-running autostart=False app are skipped."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {})
        lifecycle_service.reload_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset({"app_a"}),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.reload_app.assert_not_called()

    async def test_reimport_apps_running_autostart_false_are_reloaded(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """reimport_apps for a running autostart=False app are reconciled with force_reload."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock()}})
        lifecycle_service.reload_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset({"app_a"}),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.reload_app.assert_called_once_with("app_a", force_reload=True)

    async def test_reimport_apps_not_running_autostart_false_are_skipped(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """reimport_apps for a non-running autostart=False app are skipped."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {})
        lifecycle_service.reload_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset({"app_a"}),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.reload_app.assert_not_called()

    async def test_orphans_stopped_unconditionally(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Orphaned apps are stopped regardless of autostart."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {})
        lifecycle_service.stop_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset({"app_a"}),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.stop_app.assert_called_once_with("app_a")
