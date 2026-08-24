import asyncio
import contextlib
import typing
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.test_utils import wait_for
from hassette.test_utils.factories import make_job_registration, make_listener_registration
from hassette.test_utils.harness import HassetteHarness
from hassette.test_utils.helpers import create_listener
from hassette.types import Topic
from hassette.utils.app_utils import load_app_class_from_manifest

if typing.TYPE_CHECKING:
    from data.my_app import MyApp

    from hassette.core.app_handler import AppHandler

TEST_APPS_PATH = Path(__file__).parent.parent / "data" / "apps"


class TestApps:
    hassette: HassetteHarness
    app_handler: "AppHandler"

    @pytest.fixture(autouse=True)
    def setup(self, hassette_with_app_handler: HassetteHarness):
        self.hassette = hassette_with_app_handler
        self.app_handler = hassette_with_app_handler.app_handler

    async def test_apps_are_working(self) -> None:
        """Test actual WebSocket calls against running HA instance."""
        assert self.app_handler.registry.app_keys(), "There should be at least one app group"
        assert "my_app" in self.app_handler.registry, "my_app should be one of the app groups"
        assert "my_app_sync" in self.app_handler.registry, "my_app_sync should be one of the app groups"
        assert "disabled_app" not in self.app_handler.registry, "disabled_app should remain disabled"

        # test that an app that only has config values but no class_name/filename is ignored
        assert "myfakeapp" not in self.app_handler.registry, "myfakeapp should not be one of the app groups"

    def test_get_app_instance(self) -> None:
        """Test getting a specific app instance."""
        app = self.app_handler.get("my_app", 0)
        assert app is not None, "App instance should be found"
        assert app.app_manifest is not None, "Factory-created app should carry its manifest"

        my_app_class = load_app_class_from_manifest(app.app_manifest)

        assert isinstance(app, my_app_class), "App instance should be of type MyApp"

    def test_all_apps(self) -> None:
        """Test getting all running app instances."""
        all_apps = self.app_handler.all()
        assert isinstance(all_apps, list), "All apps should return a list"
        assert len(all_apps) == 2, "There should be at least two running app instances"
        class_names = [app.class_name for app in all_apps]
        assert "MyApp" in class_names, "MyApp should be in the list of running apps"
        assert "MyAppSync" in class_names, "MyAppSync should be in the list of running apps"

    async def test_handle_changes_does_not_lose_apps(self) -> None:
        """Verify that calling handle_changes() without config modifications preserves all running apps."""
        orig_apps = set(self.app_handler.registry.app_keys())

        event = asyncio.Event()
        results = []

        async def handler(**kwargs):
            results.append(kwargs)
            self.hassette.task_bucket.post_to_loop(event.set)

        await self.hassette.bus_service.add_listener(
            create_listener(
                handler,
                task_bucket=self.app_handler.task_bucket,
                owner_id="test",
                topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
            )
        )

        # Drain any pending APP_LOAD_COMPLETED from bootstrap_apps().
        # On Python 3.12, the BusService may not have dispatched this event yet.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.5)
        results.clear()
        event.clear()

        await self.app_handler.lifecycle.handle_change_event()

        # will timeout, because we dont fire since there are no changes
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.2)
        assert not results, f"No events should have been fired, but got: {results}"

        new_apps = set(self.app_handler.registry.app_keys())
        assert orig_apps == new_apps, "No apps should be lost during handle_changes"

    async def test_handle_changes_disables_app(self) -> None:
        """Verify that editing hassette.toml to disable an app stops the running instance."""
        assert "my_app" in self.app_handler.registry, "Precondition: my_app starts enabled"
        assert self.app_handler.registry.manifests["my_app"].enabled is True, (
            "Precondition: my_app config shows enabled"
        )

        event = asyncio.Event()

        async def handler(**kwargs):  # noqa
            self.hassette.task_bucket.post_to_loop(event.set)

        await self.hassette.bus_service.add_listener(
            create_listener(
                handler,
                task_bucket=self.app_handler.task_bucket,
                owner_id="test",
                topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
            )
        )

        with patch.object(self.app_handler.lifecycle.change_detector, "detect_changes") as mock_detect:
            mock_detect.return_value = ChangeSet(
                orphans=frozenset({"my_app"}),
                new_apps=frozenset(),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )

            await self.app_handler.lifecycle.handle_change_event()
            await asyncio.wait_for(event.wait(), timeout=1)

            assert "my_app" not in self.app_handler.registry, "my_app should stop after being disabled"
            assert "my_app_sync" in self.app_handler.registry, "Other enabled apps should continue running"

    async def test_handle_changes_enables_app(self) -> None:
        """Verify that editing hassette.toml to enable a disabled app starts the instance."""
        assert "disabled_app" not in self.app_handler.registry, "Precondition: disabled_app starts disabled"
        assert self.app_handler.registry.manifests["disabled_app"].enabled is False, (
            "Precondition: disabled_app config shows disabled"
        )

        new_app_config = deepcopy(self.app_handler.registry.manifests)
        new_app_config["disabled_app"].enabled = True

        event = asyncio.Event()

        async def handler(**kwargs):  # noqa
            self.hassette.task_bucket.post_to_loop(event.set)

        await self.hassette.bus_service.add_listener(
            create_listener(
                handler,
                task_bucket=self.app_handler.task_bucket,
                owner_id="test",
                topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
            )
        )

        with (
            patch.object(self.app_handler.lifecycle.change_detector, "detect_changes") as mock_detect,
            patch.object(self.app_handler.lifecycle, "refresh_config") as mock_refresh_config,
        ):
            self.app_handler.registry.set_manifests(new_app_config)
            mock_refresh_config.return_value = (self.app_handler.registry.manifests, new_app_config)
            mock_detect.return_value = ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset({"disabled_app"}),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )

            await self.app_handler.lifecycle.handle_change_event()
            await asyncio.wait_for(event.wait(), timeout=1)

            assert "disabled_app" in self.app_handler.registry, "disabled_app should start after being enabled"
            assert "my_app" in self.app_handler.registry, "Other enabled apps should continue running"

    async def test_config_changes_are_reflected_after_reload(self) -> None:
        """Verify that editing hassette.toml to change an app's config reloads the instance."""
        assert "my_app" in self.app_handler.registry, "Precondition: my_app starts enabled"

        my_app_instance = typing.cast("MyApp", self.app_handler.get("my_app", 0))
        assert my_app_instance is not None, "Precondition: my_app instance should exist"

        assert my_app_instance.app_config.test_entity == "input_button.test", (
            "Precondition: my_app config has initial value"
        )

        original_config = deepcopy(self.app_handler.registry.manifests)
        self.app_handler.registry.manifests["my_app"].app_config = {"test_entity": "light.office"}

        change_set = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"my_app"})
        )

        await self.app_handler.apply_changes(change_set, original_config, self.app_handler.registry.manifests)
        await wait_for(
            lambda: (
                "my_app" in self.app_handler.registry
                and self.app_handler.get("my_app", 0) is not None
                and typing.cast("MyApp", self.app_handler.get("my_app", 0)).app_config.test_entity == "light.office"
            ),
            desc="app reload completed with updated config",
        )

        assert "my_app" in self.app_handler.registry, "my_app should still be running after reload"
        my_app_instance = typing.cast("MyApp", self.app_handler.get("my_app", 0))
        assert my_app_instance is not None, "my_app instance should still exist after reload"
        assert my_app_instance.app_config.test_entity == "light.office", "my_app config should be updated after reload"

    async def test_app_with_instance_name(self) -> None:
        """Test that an app with a specific instance_name in config starts correctly."""
        assert "my_app" in self.app_handler.registry, "Precondition: my_app starts enabled"

        my_app_instance = self.app_handler.get("my_app", 0)
        assert my_app_instance is not None, "my_app instance should exist"
        assert my_app_instance.app_config.instance_name == "unique_instance_name", (
            "my_app instance should have the specified instance_name"
        )

    async def test_app_without_instance_name(self) -> None:
        """Test that an app without a specific instance_name in config starts with default naming."""
        assert "my_app_sync" in self.app_handler.registry, "Precondition: my_app_sync starts enabled"

        expected_name = "MyAppSync.0"

        my_app_sync_instance = self.app_handler.get("my_app_sync", 0)
        assert my_app_sync_instance is not None, "my_app_sync instance should exist"
        assert my_app_sync_instance.app_config.instance_name == expected_name, (
            f"my_app_sync instance should have the default instance_name {expected_name},"
            f" found {my_app_sync_instance.app_config.instance_name}"
        )

    async def test_autostart_false_app_absent_after_bootstrap(self) -> None:
        """After bootstrap, an enabled+autostart=false app has no running instances."""
        assert "no_autostart_app" not in self.app_handler.registry, (
            "no_autostart_app should not be running after bootstrap (autostart=false)"
        )

    def test_autostart_false_app_status_is_stopped(self) -> None:
        """autostart=false app reports status=stopped and autostart=False in snapshot."""
        assert "no_autostart_app" not in self.app_handler.registry, (
            "Precondition: no_autostart_app must not be running for status to read 'stopped'"
        )
        snapshot = self.app_handler.registry.get_full_snapshot()
        manifest_info = next((m for m in snapshot.manifests if m.app_key == "no_autostart_app"), None)
        assert manifest_info is not None, "no_autostart_app should appear in the snapshot"
        assert manifest_info.status == "stopped", f"Expected status='stopped', got {manifest_info.status!r}"
        assert manifest_info.autostart is False, f"Expected autostart=False, got {manifest_info.autostart!r}"

    async def test_start_app_starts_autostart_false_app(self) -> None:
        """start_app() explicitly starts an autostart=false app."""
        assert "no_autostart_app" not in self.app_handler.registry, "Precondition: not running"

        await self.app_handler.lifecycle.start_app("no_autostart_app")

        assert "no_autostart_app" in self.app_handler.registry, (
            "no_autostart_app should be running after explicit start_app() call"
        )

    async def test_start_remains_allowed_after_disconnect_once_bootstrap_released(self) -> None:
        await self.app_handler.stop_app("my_app_sync")

        await self.hassette.state_proxy.on_disconnect()
        await self.app_handler.start_app("my_app_sync")

        assert "my_app_sync" in self.app_handler.registry

    async def test_disconnect_after_release_leaves_running_apps_registered(self) -> None:
        """A runtime disconnect after bootstrap release does not stop or suspend running apps.

        The bootstrap coordinator makes a one-time release decision rather than continuously
        enforcing capabilities, so an already-running app instance must stay registered (same
        instance, not restarted) across a post-release disconnect.
        """
        assert "my_app" in self.app_handler.registry, "Precondition: my_app is running"
        my_app_instance_before = self.app_handler.get("my_app", 0)
        assert my_app_instance_before is not None

        await self.hassette.state_proxy.on_disconnect()

        assert "my_app" in self.app_handler.registry, "my_app must remain registered after disconnect"
        my_app_instance_after = self.app_handler.get("my_app", 0)
        assert my_app_instance_after is my_app_instance_before, "The same running instance must be preserved"
        assert my_app_instance_after.is_ready()

    async def test_manual_start_reload_still_allowed_after_disconnect_when_already_released(self) -> None:
        """Once bootstrap has released, later disconnects never re-block start/reload.

        Complements ``test_start_remains_allowed_after_disconnect_once_bootstrap_released``
        (which restarts an app that was manually stopped first) by proving reload on an
        app that stayed running through the disconnect is also unaffected.
        """
        await self.hassette.state_proxy.on_disconnect()

        await self.app_handler.reload_app("my_app_sync", force_reload=False)

        assert "my_app_sync" in self.app_handler.registry

    async def test_new_app_changeset_does_not_start_autostart_false_app(self) -> None:
        """A reload ChangeSet with new_apps containing an autostart=false app leaves it unstarted."""
        assert "no_autostart_app" not in self.app_handler.registry, "Precondition: not running"

        event = asyncio.Event()

        async def handler(**kwargs):  # noqa
            self.hassette.task_bucket.post_to_loop(event.set)

        await self.hassette.bus_service.add_listener(
            create_listener(
                handler,
                task_bucket=self.app_handler.task_bucket,
                owner_id="test",
                topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
            )
        )

        new_app_config = deepcopy(self.app_handler.registry.manifests)

        with (
            patch.object(self.app_handler.lifecycle.change_detector, "detect_changes") as mock_detect,
            patch.object(self.app_handler.lifecycle, "refresh_config") as mock_refresh_config,
        ):
            self.app_handler.registry.set_manifests(new_app_config)
            mock_refresh_config.return_value = (self.app_handler.registry.manifests, new_app_config)
            mock_detect.return_value = ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset({"no_autostart_app"}),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )

            await self.app_handler.lifecycle.handle_change_event()
            await asyncio.wait_for(event.wait(), timeout=1)

            assert "no_autostart_app" not in self.app_handler.registry, (
                "no_autostart_app should remain unstarted after reload with new_apps (autostart=false)"
            )

    async def test_unrelated_reload_leaves_manually_started_autostart_false_app_running(self) -> None:
        """A reload that changes an unrelated app leaves an already-running autostart=false app running."""
        await self.app_handler.lifecycle.start_app("no_autostart_app")
        assert "no_autostart_app" in self.app_handler.registry, "Precondition: no_autostart_app is manually running"

        event = asyncio.Event()

        async def handler(**kwargs):  # noqa
            self.hassette.task_bucket.post_to_loop(event.set)

        await self.hassette.bus_service.add_listener(
            create_listener(
                handler,
                task_bucket=self.app_handler.task_bucket,
                owner_id="test",
                topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
            )
        )

        new_app_config = deepcopy(self.app_handler.registry.manifests)
        new_app_config["my_app"].app_config = {"test_entity": "light.some_other_light"}

        with (
            patch.object(self.app_handler.lifecycle.change_detector, "detect_changes") as mock_detect,
            patch.object(self.app_handler.lifecycle, "refresh_config") as mock_refresh_config,
        ):
            self.app_handler.registry.set_manifests(new_app_config)
            mock_refresh_config.return_value = (self.app_handler.registry.manifests, new_app_config)
            mock_detect.return_value = ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset(),
                reimport_apps=frozenset(),
                reload_apps=frozenset({"my_app"}),
            )

            await self.app_handler.lifecycle.handle_change_event()
            await asyncio.wait_for(event.wait(), timeout=1)

            assert "no_autostart_app" in self.app_handler.registry, (
                "no_autostart_app should still be running after an unrelated reload"
            )

    async def test_reload_of_not_running_autostart_false_app_leaves_it_unstarted(self) -> None:
        """A reload with reload_apps containing an autostart=false app that is not running leaves it unstarted."""
        assert "no_autostart_app" not in self.app_handler.registry, "Precondition: not running"

        event = asyncio.Event()

        async def handler(**kwargs):  # noqa
            self.hassette.task_bucket.post_to_loop(event.set)

        await self.hassette.bus_service.add_listener(
            create_listener(
                handler,
                task_bucket=self.app_handler.task_bucket,
                owner_id="test",
                topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
            )
        )

        new_app_config = deepcopy(self.app_handler.registry.manifests)
        new_app_config["no_autostart_app"].app_config = {"test_entity": "light.changed"}

        with (
            patch.object(self.app_handler.lifecycle.change_detector, "detect_changes") as mock_detect,
            patch.object(self.app_handler.lifecycle, "refresh_config") as mock_refresh_config,
        ):
            self.app_handler.registry.set_manifests(new_app_config)
            mock_refresh_config.return_value = (self.app_handler.registry.manifests, new_app_config)
            mock_detect.return_value = ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset(),
                reimport_apps=frozenset(),
                reload_apps=frozenset({"no_autostart_app"}),
            )

            await self.app_handler.lifecycle.handle_change_event()
            await asyncio.wait_for(event.wait(), timeout=1)

            assert "no_autostart_app" not in self.app_handler.registry, (
                "no_autostart_app should remain unstarted after config change reload (autostart=false, not running)"
            )

    async def test_reload_of_running_autostart_false_app_leaves_it_running(self) -> None:
        """A reload of a running autostart=false app that had config changes reloads and keeps it running."""
        await self.app_handler.lifecycle.start_app("no_autostart_app")
        assert "no_autostart_app" in self.app_handler.registry, "Precondition: no_autostart_app is running"

        original_app_config = deepcopy(self.app_handler.registry.manifests)
        new_app_config = deepcopy(self.app_handler.registry.manifests)
        new_app_config["no_autostart_app"].app_config = {"test_entity": "light.changed"}
        self.app_handler.registry.set_manifests(new_app_config)

        change_set = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset({"no_autostart_app"}),
        )

        await self.app_handler.apply_changes(change_set, original_app_config, new_app_config)
        await wait_for(
            lambda: "no_autostart_app" in self.app_handler.registry,
            desc="no_autostart_app still running after reload",
        )

        assert "no_autostart_app" in self.app_handler.registry, (
            "no_autostart_app should still be running after reload of its config"
        )

    async def test_autostart_true_apps_start_at_boot(self) -> None:
        """Apps without an autostart key (default True) still start at boot."""
        assert "my_app" in self.app_handler.registry, "my_app (no autostart key) should start at boot"
        assert "my_app_sync" in self.app_handler.registry, "my_app_sync (no autostart key) should start at boot"

    def test_disabled_app_absent_and_disabled_status(self) -> None:
        """disabled_app is absent from the registry and reports disabled status."""
        assert "disabled_app" not in self.app_handler.registry, "disabled_app should remain absent"
        snapshot = self.app_handler.registry.get_full_snapshot()
        manifest_info = next((m for m in snapshot.manifests if m.app_key == "disabled_app"), None)
        assert manifest_info is not None, "disabled_app should appear in snapshot"
        assert manifest_info.status == "disabled", f"Expected status='disabled', got {manifest_info.status!r}"


class TestPerInstanceSelectiveRestart:
    """Selective per-instance restart on config change and via reload_instance() (#796).

    Uses a fresh ``AppLifecycleService`` + ``AppRegistry`` so the ``multi_instance`` manifest
    here never touches the shared ``hassette_with_app_handler`` registry that ``TestApps``
    asserts app counts against. Reuses that fixture's already-wired ``Hassette`` instance
    (rather than constructing a second ``HassetteHarness``) because only one harness may hold
    the process-global Hassette context at a time — see ``real_db_lifecycle`` below.
    """

    MULTI_INSTANCE_APP_KEY = "multi_instance"

    def _make_manifest(self, app_config: list[dict]) -> AppManifest:
        return AppManifest(
            app_key=self.MULTI_INSTANCE_APP_KEY,
            filename="multi_instance_app.py",
            class_name="MultiInstanceApp",
            app_dir=TEST_APPS_PATH,
            config=app_config,
            enabled=True,
            display_name="Multi Instance",
            full_path=TEST_APPS_PATH / "multi_instance_app.py",
        )

    @pytest.fixture
    async def real_db_lifecycle(
        self, hassette_with_app_handler: HassetteHarness
    ) -> typing.AsyncIterator[tuple[AppLifecycleService, CommandExecutor, DatabaseService]]:
        """A fresh ``AppLifecycleService`` wired to a real DB-backed ``CommandExecutor``.

        ``HassetteHarness`` normally mocks ``CommandExecutor`` entirely for bus/scheduler/
        app-handler components (see ``harness.py`` ``_start_bus``/``_start_scheduler``/
        ``_start_app_handler``) — listener/job registrations never persist to a real
        database. Swapping in a real ``CommandExecutor`` (backed by a real ``DatabaseService``)
        on the module-scoped harness's ``Hassette`` lets ``reconcile_app_registrations()`` run
        its real reconciliation SQL, which the DB-survival test below needs to observe. The
        swap is restored in the ``finally`` block so ``TestApps``'s other tests keep seeing the
        harness's normal mock.

        A second, independently-constructed ``HassetteHarness``/``Hassette`` was tried first but
        collides on the process-global Hassette context (``context.set_global_hassette``) while
        this module's own ``hassette_with_app_handler`` harness is still alive — only one
        ``Hassette`` instance may hold that context at a time.
        """
        hassette = hassette_with_app_handler.hassette
        original_command_executor = hassette._command_executor
        original_database_service = hassette._database_service

        db_service = DatabaseService(hassette, parent=hassette)
        await db_service.on_initialize()
        hassette._database_service = db_service

        executor = CommandExecutor(hassette, parent=hassette)
        await executor.on_initialize()
        hassette._command_executor = executor

        registry = AppRegistry()
        lifecycle = AppLifecycleService(hassette, parent=None, registry=registry)

        try:
            yield lifecycle, executor, db_service
        finally:
            await lifecycle.shutdown_all()
            await executor.on_shutdown()
            await db_service.on_shutdown()
            hassette._command_executor = original_command_executor
            hassette._database_service = original_database_service

    async def test_selective_restart_reloads_only_changed_instance(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        """A config change to one instance restarts only that instance.

        The sibling instance keeps running undisturbed — same object identity, not recreated.
        """
        lifecycle, _executor, _db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        original_manifest = self._make_manifest([{"value": "a"}, {"value": "b"}])
        lifecycle.set_apps_configs({app_key: original_manifest})

        await lifecycle.start_app(app_key)

        instance0_before = lifecycle.registry.get(app_key, 0)
        instance1_before = lifecycle.registry.get(app_key, 1)
        assert instance0_before is not None, "Precondition: instance 0 should be running"
        assert instance1_before is not None, "Precondition: instance 1 should be running"

        original_config = deepcopy(lifecycle.registry.manifests)
        # Mutate instance 1's config only — instance 0's dict stays identical.
        lifecycle.registry.manifests[app_key].app_config = [{"value": "a"}, {"value": "changed"}]

        change_set = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({app_key})
        )
        await lifecycle.apply_changes(change_set, original_config, lifecycle.registry.manifests)

        await wait_for(
            lambda: (
                lifecycle.registry.get(app_key, 1) is not None
                and lifecycle.registry.get(app_key, 1).app_config.value == "changed"
            ),
            desc="instance 1 reloaded with updated config",
        )

        instance0_after = lifecycle.registry.get(app_key, 0)
        instance1_after = lifecycle.registry.get(app_key, 1)
        assert instance0_after is instance0_before, (
            "instance 0 should not have been recreated — sibling instance must stay undisturbed"
        )
        assert instance1_after is not None
        assert instance1_after is not instance1_before, "instance 1 should have been recreated"
        assert instance1_after.app_config.value == "changed", "instance 1 should reflect the new config"

    async def test_reload_instance_preserves_sibling_db_rows(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        """reload_instance() must not retire sibling instances' listener/job DB rows.

        MultiInstanceApp registers no listeners/jobs of its own, so both instances' rows are
        seeded directly via CommandExecutor to give the reconciliation SQL real rows to scope
        against. After reload_instance(app_key, 1), instance 0's rows must survive unchanged
        while instance 1's stale rows (nothing "live" after its own reload) are cleaned up —
        proving the reconciliation SQL is scoped by instance_index, not just app_key.
        """
        lifecycle, executor, db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        manifest = self._make_manifest([{"value": "a"}, {"value": "b"}])
        lifecycle.set_apps_configs({app_key: manifest})

        await lifecycle.start_app(app_key)
        assert lifecycle.registry.get(app_key, 0) is not None, "Precondition: instance 0 should be running"
        assert lifecycle.registry.get(app_key, 1) is not None, "Precondition: instance 1 should be running"

        listener0_id = await executor.register_listener(
            make_listener_registration(app_key=app_key, instance_index=0, name="sibling_listener")
        )
        job0_id = await executor.register_job(
            make_job_registration(app_key=app_key, instance_index=0, job_name="sibling_job")
        )
        listener1_id = await executor.register_listener(
            make_listener_registration(app_key=app_key, instance_index=1, name="reloaded_listener")
        )
        job1_id = await executor.register_job(
            make_job_registration(app_key=app_key, instance_index=1, job_name="reloaded_job")
        )

        await lifecycle.reload_instance(app_key, 1)

        listener0_cursor = await db_service.db.execute(
            "SELECT id, retired_at FROM listeners WHERE id = ?", (listener0_id,)
        )
        listener0_row = await listener0_cursor.fetchone()
        assert listener0_row is not None, "sibling instance 0's listener row must survive reload of instance 1"
        assert listener0_row["retired_at"] is None, "sibling instance 0's listener row must not be retired"

        job0_cursor = await db_service.db.execute("SELECT id, retired_at FROM scheduled_jobs WHERE id = ?", (job0_id,))
        job0_row = await job0_cursor.fetchone()
        assert job0_row is not None, "sibling instance 0's job row must survive reload of instance 1"
        assert job0_row["retired_at"] is None, "sibling instance 0's job row must not be retired"

        listener1_cursor = await db_service.db.execute("SELECT id FROM listeners WHERE id = ?", (listener1_id,))
        assert await listener1_cursor.fetchone() is None, (
            "instance 1's stale listener row should be cleaned up by its own reload"
        )

        job1_cursor = await db_service.db.execute("SELECT id FROM scheduled_jobs WHERE id = ?", (job1_id,))
        assert await job1_cursor.fetchone() is None, "instance 1's stale job row should be cleaned up by its own reload"
