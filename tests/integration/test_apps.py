import asyncio
import contextlib
import typing
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_common import ActionOutcomes
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.testing import HassetteHarness, wait_for
from hassette.types import Topic
from hassette.utils.app_utils import load_app_class_from_manifest
from tests.support.factories import make_change_set, make_job_registration, make_listener_registration
from tests.support.helpers import create_listener, noop

if typing.TYPE_CHECKING:
    from hassette.core.app_handler import AppHandler
    from tests.data.apps.my_app import MyApp

TEST_APPS_PATH = Path(__file__).parent.parent / "data" / "apps"


class TestApps:
    hassette: HassetteHarness
    app_handler: "AppHandler"

    @pytest.fixture(autouse=True)
    def setup(self, hassette_with_app_handler: HassetteHarness):
        self.hassette = hassette_with_app_handler
        self.app_handler = hassette_with_app_handler.app_handler

    async def on_load_completed(self) -> asyncio.Event:
        """Subscribe to APP_LOAD_COMPLETED and return an Event set the next time it fires."""
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
        return event

    async def run_change_event(
        self,
        changes: ChangeSet,
        *,
        new_manifests: dict[str, AppManifest] | None = None,
        timeout: float = 1,
    ) -> None:
        """Force one reconciliation pass with `changes` and wait for APP_LOAD_COMPLETED.

        When `new_manifests` is given, refresh_config is stubbed to return it — the shape the
        file-watcher path produces — instead of re-reading hassette.toml.
        """
        event = await self.on_load_completed()

        with contextlib.ExitStack() as stack:
            mock_detect = stack.enter_context(
                patch.object(self.app_handler.lifecycle.change_detector, "detect_changes")
            )
            mock_detect.return_value = changes

            if new_manifests is not None:
                mock_refresh_config = stack.enter_context(patch.object(self.app_handler.lifecycle, "refresh_config"))
                self.app_handler.registry.set_manifests(new_manifests)
                mock_refresh_config.return_value = (self.app_handler.registry.manifests, new_manifests)

            await self.app_handler.lifecycle.handle_change_event()
            await asyncio.wait_for(event.wait(), timeout=timeout)

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
        app = self.app_handler.get("my_app")
        assert app is not None, "App instance should be found"
        assert app.app_manifest is not None, "Factory-created app should carry its manifest"

        my_app_class = load_app_class_from_manifest(app.app_manifest, config=app.hassette.config)

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

        results = []

        async def handler(**kwargs):
            results.append(kwargs)
            self.hassette.task_bucket.post_to_loop(event.set)

        event = asyncio.Event()
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

        await self.run_change_event(make_change_set(orphans={"my_app"}))

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

        await self.run_change_event(make_change_set(new_apps={"disabled_app"}), new_manifests=new_app_config)

        assert "disabled_app" in self.app_handler.registry, "disabled_app should start after being enabled"
        assert "my_app" in self.app_handler.registry, "Other enabled apps should continue running"

    async def test_config_changes_are_reflected_after_reload(self) -> None:
        """Verify that editing hassette.toml to change an app's config reloads the instance."""
        assert "my_app" in self.app_handler.registry, "Precondition: my_app starts enabled"

        my_app_instance = typing.cast("MyApp", self.app_handler.get("my_app"))
        assert my_app_instance is not None, "Precondition: my_app instance should exist"

        assert my_app_instance.app_config.test_entity == "input_button.test", (
            "Precondition: my_app config has initial value"
        )

        original_config = deepcopy(self.app_handler.registry.manifests)
        self.app_handler.registry.manifests["my_app"].app_config = {
            "test_entity": "light.office",
            "instance_name": "unique_instance_name",
        }

        changes = make_change_set(reload_apps={"my_app"})

        await self.app_handler.apply_changes(changes, original_config, self.app_handler.registry.manifests)
        await wait_for(
            lambda: (
                "my_app" in self.app_handler.registry
                and self.app_handler.get("my_app") is not None
                and typing.cast("MyApp", self.app_handler.get("my_app")).app_config.test_entity == "light.office"
            ),
            desc="app reload completed with updated config",
        )

        assert "my_app" in self.app_handler.registry, "my_app should still be running after reload"
        my_app_instance = typing.cast("MyApp", self.app_handler.get("my_app"))
        assert my_app_instance is not None, "my_app instance should still exist after reload"
        assert my_app_instance.app_config.test_entity == "light.office", "my_app config should be updated after reload"

    async def test_app_with_instance_name(self) -> None:
        """Test that an app with a specific instance_name in config starts correctly."""
        assert "my_app" in self.app_handler.registry, "Precondition: my_app starts enabled"

        my_app_instance = self.app_handler.get("my_app", "unique_instance_name")
        assert my_app_instance is not None, "my_app instance should exist"
        assert my_app_instance.app_config.instance_name == "unique_instance_name", (
            "my_app instance should have the specified instance_name"
        )

    async def test_app_instance_name_is_its_unique_name(self) -> None:
        """A configured app runs under exactly the instance_name its config sets, which is also its unique_name."""
        assert "my_app_sync" in self.app_handler.registry, "Precondition: my_app_sync starts enabled"

        instance = self.app_handler.get("my_app_sync", "my_app_sync")
        assert instance is not None, "my_app_sync instance should exist"
        assert instance.app_config.instance_name == "my_app_sync"
        assert instance.unique_name == "my_app_sync"

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
        my_app_instance_before = self.app_handler.get("my_app")
        assert my_app_instance_before is not None

        await self.hassette.state_proxy.on_disconnect()

        assert "my_app" in self.app_handler.registry, "my_app must remain registered after disconnect"
        my_app_instance_after = self.app_handler.get("my_app")
        assert my_app_instance_after is my_app_instance_before, "The same running instance must be preserved"
        assert my_app_instance_after is not None
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

        new_app_config = deepcopy(self.app_handler.registry.manifests)

        await self.run_change_event(make_change_set(new_apps={"no_autostart_app"}), new_manifests=new_app_config)

        assert "no_autostart_app" not in self.app_handler.registry, (
            "no_autostart_app should remain unstarted after reload with new_apps (autostart=false)"
        )

    async def test_unrelated_reload_leaves_manually_started_autostart_false_app_running(self) -> None:
        """A reload that changes an unrelated app leaves an already-running autostart=false app running."""
        await self.app_handler.lifecycle.start_app("no_autostart_app")
        assert "no_autostart_app" in self.app_handler.registry, "Precondition: no_autostart_app is manually running"

        new_app_config = deepcopy(self.app_handler.registry.manifests)
        new_app_config["my_app"].app_config = {
            "test_entity": "light.some_other_light",
            "instance_name": "unique_instance_name",
        }

        await self.run_change_event(make_change_set(reload_apps={"my_app"}), new_manifests=new_app_config)

        assert "no_autostart_app" in self.app_handler.registry, (
            "no_autostart_app should still be running after an unrelated reload"
        )

    async def test_reload_of_not_running_autostart_false_app_leaves_it_unstarted(self) -> None:
        """A reload with reload_apps containing an autostart=false app that is not running leaves it unstarted."""
        assert "no_autostart_app" not in self.app_handler.registry, "Precondition: not running"

        new_app_config = deepcopy(self.app_handler.registry.manifests)
        new_app_config["no_autostart_app"].app_config = {
            "test_entity": "light.changed",
            "instance_name": "no_autostart_instance",
        }

        await self.run_change_event(make_change_set(reload_apps={"no_autostart_app"}), new_manifests=new_app_config)

        assert "no_autostart_app" not in self.app_handler.registry, (
            "no_autostart_app should remain unstarted after config change reload (autostart=false, not running)"
        )

    async def test_reload_of_running_autostart_false_app_leaves_it_running(self) -> None:
        """A reload of a running autostart=false app that had config changes reloads and keeps it running."""
        await self.app_handler.lifecycle.start_app("no_autostart_app")
        assert "no_autostart_app" in self.app_handler.registry, "Precondition: no_autostart_app is running"

        original_app_config = deepcopy(self.app_handler.registry.manifests)
        new_app_config = deepcopy(self.app_handler.registry.manifests)
        new_app_config["no_autostart_app"].app_config = {
            "test_entity": "light.changed",
            "instance_name": "no_autostart_instance",
        }
        self.app_handler.registry.set_manifests(new_app_config)

        changes = make_change_set(reload_apps={"no_autostart_app"})

        await self.app_handler.apply_changes(changes, original_app_config, new_app_config)
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
            app_config=app_config,
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
        original_manifest = self._make_manifest(
            [{"value": "a", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta"}]
        )
        lifecycle.set_apps_configs({app_key: original_manifest})

        await lifecycle.start_app(app_key)

        alpha_before = lifecycle.registry.get(app_key, "alpha")
        beta_before = lifecycle.registry.get(app_key, "beta")
        assert alpha_before is not None, "Precondition: alpha should be running"
        assert beta_before is not None, "Precondition: beta should be running"

        original_config = deepcopy(lifecycle.registry.manifests)
        # Mutate beta's config only — alpha's dict stays identical.
        lifecycle.registry.manifests[app_key].app_config = [
            {"value": "a", "instance_name": "alpha"},
            {"value": "changed", "instance_name": "beta"},
        ]

        changes = make_change_set(reload_apps={app_key})
        await lifecycle.apply_changes(changes, original_config, lifecycle.registry.manifests)

        await wait_for(
            lambda: (
                (beta := lifecycle.registry.get(app_key, "beta")) is not None
                and beta.app_config.model_dump()["value"] == "changed"
            ),
            desc="beta reloaded with updated config",
        )

        alpha_after = lifecycle.registry.get(app_key, "alpha")
        beta_after = lifecycle.registry.get(app_key, "beta")
        assert alpha_after is alpha_before, (
            "alpha should not have been recreated — sibling instance must stay undisturbed"
        )
        assert beta_after is not None
        assert beta_after is not beta_before, "beta should have been recreated"
        assert beta_after.app_config.model_dump()["value"] == "changed", "beta should reflect the new config"

    async def _apply_config(self, lifecycle: AppLifecycleService, app_config: list[dict]) -> None:
        """Change the multi-instance app's config and apply it the way a live config reload does."""
        original_config = deepcopy(lifecycle.registry.manifests)
        lifecycle.registry.manifests[self.MULTI_INSTANCE_APP_KEY].app_config = app_config
        changes = make_change_set(reload_apps={self.MULTI_INSTANCE_APP_KEY})
        await lifecycle.apply_changes(changes, original_config, lifecycle.registry.manifests)

    async def test_reorder_restarts_nothing_and_each_instance_keeps_its_records(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        """Moving config blocks leaves every instance running; only the display order changes."""
        lifecycle, _executor, _db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        alpha_config = {"value": "a", "instance_name": "alpha"}
        beta_config = {"value": "b", "instance_name": "beta"}
        lifecycle.set_apps_configs({app_key: self._make_manifest([alpha_config, beta_config])})
        await lifecycle.start_app(app_key)
        alpha, beta = lifecycle.registry.get(app_key, "alpha"), lifecycle.registry.get(app_key, "beta")
        assert alpha is not None
        assert beta is not None

        await self._apply_config(lifecycle, [beta_config, alpha_config])

        assert lifecycle.registry.get(app_key, "alpha") is alpha
        assert lifecycle.registry.get(app_key, "beta") is beta
        assert alpha.index == 0, "a running instance's index stays as constructed until #3100 decides its future"
        manifest = lifecycle.registry.get_manifest(app_key)
        assert manifest is not None
        instances = lifecycle.registry.build_manifest_info(app_key, manifest).instances
        assert [(info.index, info.instance_name) for info in instances] == [(0, "beta"), (1, "alpha")]

    async def test_adding_an_instance_starts_only_it(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        lifecycle, _executor, _db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        alpha_config = {"value": "a", "instance_name": "alpha"}
        lifecycle.set_apps_configs({app_key: self._make_manifest([alpha_config])})
        await lifecycle.start_app(app_key)
        alpha = lifecycle.registry.get(app_key, "alpha")

        await self._apply_config(lifecycle, [{"value": "b", "instance_name": "beta"}, alpha_config])

        assert lifecycle.registry.get(app_key, "alpha") is alpha, "the unchanged sibling keeps running"
        beta = lifecycle.registry.get(app_key, "beta")
        assert beta is not None
        assert beta.index == 0, "a new instance is constructed with its position in the config"

    @pytest.mark.parametrize(
        "new_config",
        [
            [{"value": "a", "instance_name": "alpha"}],
            [{"value": "a", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta_renamed"}],
        ],
        ids=["removed", "renamed"],
    )
    async def test_a_name_leaving_the_config_stops_alone_and_its_rows_retire_at_the_reload(
        self,
        real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService],
        monkeypatch: pytest.MonkeyPatch,
        new_config: list[dict],
    ) -> None:
        """Its listener stops counting as active without waiting for a retention cycle, and is not deleted."""
        lifecycle, executor, db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        lifecycle.set_apps_configs(
            {
                app_key: self._make_manifest(
                    [{"value": "a", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta"}]
                )
            }
        )
        await lifecycle.start_app(app_key)
        alpha = lifecycle.registry.get(app_key, "alpha")
        registered = {
            name: await executor.register_listener(
                make_listener_registration(instance_name=name, app_key=app_key, instance_index=0, name=f"{name}_l")
            )
            for name in ("alpha", "beta")
        }
        # This lifecycle's registry isn't the harness's, so the database reads this app's live set from it.
        monkeypatch.setattr(
            db_service,
            "live_instances",
            lambda: (
                [(app_key, config["instance_name"]) for config in new_config]
                + [(app_key, name) for name in lifecycle.registry.get_running_apps(app_key)]
            ),
        )

        await self._apply_config(lifecycle, new_config)

        assert lifecycle.registry.get(app_key, "alpha") is alpha, "the unchanged sibling keeps running"
        assert lifecycle.registry.get(app_key, "beta") is None

        async def retired_at(listener_id: int | None) -> float | None:
            cursor = await db_service.db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
            row = await cursor.fetchone()
            assert row is not None, "retiring must keep the row, so a queued execution keeps its parent"
            return row["retired_at"]

        beta_retired_at = None
        for _ in range(200):
            beta_retired_at = await retired_at(registered["beta"])
            if beta_retired_at is not None:
                break
            await asyncio.sleep(0.01)
        assert beta_retired_at is not None
        assert await retired_at(registered["alpha"]) is None

    async def test_reload_instance_preserves_sibling_db_rows(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        """reload_instance() must not retire sibling instances' listener/job DB rows.

        MultiInstanceApp registers no listeners/jobs of its own, so both instances' rows are
        seeded directly via CommandExecutor to give the reconciliation SQL real rows to scope
        against. After reload_instance(app_key, "beta"), alpha's rows must survive unchanged
        while beta's stale rows (nothing "live" after its own reload) are cleaned up —
        proving the reconciliation SQL is scoped by instance_name, not just app_key.
        """
        lifecycle, executor, db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        manifest = self._make_manifest(
            [{"value": "a", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta"}]
        )
        lifecycle.set_apps_configs({app_key: manifest})

        await lifecycle.start_app(app_key)
        assert lifecycle.registry.get(app_key, "alpha") is not None, "Precondition: alpha should be running"
        assert lifecycle.registry.get(app_key, "beta") is not None, "Precondition: beta should be running"

        listener0_id = await executor.register_listener(
            make_listener_registration(
                instance_name=lifecycle.registry.instance_name(app_key, 0),
                app_key=app_key,
                instance_index=0,
                name="sibling_listener",
            )
        )
        job0_id = await executor.register_job(
            make_job_registration(
                instance_name=lifecycle.registry.instance_name(app_key, 0),
                app_key=app_key,
                instance_index=0,
                job_name="sibling_job",
            )
        )
        listener1_id = await executor.register_listener(
            make_listener_registration(
                instance_name=lifecycle.registry.instance_name(app_key, 1),
                app_key=app_key,
                instance_index=1,
                name="reloaded_listener",
            )
        )
        job1_id = await executor.register_job(
            make_job_registration(
                instance_name=lifecycle.registry.instance_name(app_key, 1),
                app_key=app_key,
                instance_index=1,
                job_name="reloaded_job",
            )
        )

        await lifecycle.reload_instance(app_key, "beta")

        listener0_cursor = await db_service.db.execute(
            "SELECT id, retired_at FROM listeners WHERE id = ?", (listener0_id,)
        )
        listener0_row = await listener0_cursor.fetchone()
        assert listener0_row is not None, "sibling alpha's listener row must survive reload of beta"
        assert listener0_row["retired_at"] is None, "sibling alpha's listener row must not be retired"

        job0_cursor = await db_service.db.execute("SELECT id, retired_at FROM scheduled_jobs WHERE id = ?", (job0_id,))
        job0_row = await job0_cursor.fetchone()
        assert job0_row is not None, "sibling alpha's job row must survive reload of beta"
        assert job0_row["retired_at"] is None, "sibling alpha's job row must not be retired"

        listener1_cursor = await db_service.db.execute("SELECT id FROM listeners WHERE id = ?", (listener1_id,))
        assert await listener1_cursor.fetchone() is None, (
            "beta's stale listener row should be cleaned up by its own reload"
        )

        job1_cursor = await db_service.db.execute("SELECT id FROM scheduled_jobs WHERE id = ?", (job1_id,))
        assert await job1_cursor.fetchone() is None, "beta's stale job row should be cleaned up by its own reload"

    async def test_batch_reload_stops_every_instance_before_creating_any_replacement(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        """Regression test for PR #1687 review finding: a batch reload can make a *new* instance take an
        ``instance_name`` (and therefore ``App.unique_name``/owner_id) still held by a running instance —
        here ``beta`` keeps its name with a new config while ``alpha`` leaves and ``gamma`` arrives. Bus owner
        registries (``BusService.router``, ``BusService._removal_callbacks``) are keyed by that name string
        alone, so a create that ran before the old ``beta`` finished tearing down could register a listener
        that the old teardown's ``remove_listeners_by_owner("beta")`` then rips out too, since both are
        indistinguishable by owner_id alone.

        Proven deterministically by delaying ``beta``'s stop and observing that no create is ever attempted
        while that stop is still pending — the stop-all-then-create-all split makes this ordering structural,
        not timing-dependent. A reload that interleaved each instance's stop-then-create would start
        ``gamma``'s create immediately, well before ``beta``'s delayed stop completes.
        """
        lifecycle, _executor, _db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        original_manifest = self._make_manifest(
            [
                {"value": "a", "instance_name": "alpha"},
                {"value": "b", "instance_name": "beta"},
            ]
        )
        lifecycle.set_apps_configs({app_key: original_manifest})

        await lifecycle.start_app(app_key)
        beta_before = lifecycle.registry.get(app_key, "beta")
        assert beta_before is not None, "Precondition: beta should be running"
        assert beta_before.unique_name == "beta"

        original_config = deepcopy(lifecycle.registry.manifests)
        # One edit: alpha leaves the config, beta takes a new config, gamma arrives.
        lifecycle.registry.manifests[app_key].app_config = [
            {"value": "b2", "instance_name": "beta"},
            {"value": "c", "instance_name": "gamma"},
        ]

        call_order: list[str] = []
        beta_stop_entered = asyncio.Event()
        release_beta_stop = asyncio.Event()

        orig_stop = lifecycle._stop_instance_unlocked
        orig_create = lifecycle._create_instance_unlocked

        async def instrumented_stop(app_key: str, instance_name: str, *, outcomes: ActionOutcomes) -> None:
            if instance_name == "beta":
                beta_stop_entered.set()
                await release_beta_stop.wait()
            await orig_stop(app_key, instance_name, outcomes=outcomes)
            call_order.append(f"stop_{instance_name}_done")

        async def instrumented_create(
            app_key: str,
            instance_name: str,
            app_manifest: AppManifest,
            force_reload: bool = False,
            *,
            outcomes: ActionOutcomes,
        ) -> None:
            call_order.append(f"create_{instance_name}_start")
            await orig_create(app_key, instance_name, app_manifest, force_reload, outcomes=outcomes)

        lifecycle._stop_instance_unlocked = instrumented_stop
        lifecycle._create_instance_unlocked = instrumented_create

        changes = make_change_set(reload_apps={app_key})
        task = asyncio.create_task(lifecycle.apply_changes(changes, original_config, lifecycle.registry.manifests))

        await asyncio.wait_for(beta_stop_entered.wait(), timeout=1)
        # While beta's stop of the old, name-colliding instance is still pending, no create for any
        # instance may have started yet — the stop-all-then-create-all split forbids it structurally,
        # not just by timing luck.
        await asyncio.sleep(0)  # let any wrongly-scheduled create task get a chance to run
        assert not any(entry.startswith("create_") for entry in call_order), (
            f"a create started before beta's stop finished: {call_order}"
        )
        assert not task.done()

        release_beta_stop.set()
        await asyncio.wait_for(task, timeout=2)

        # Every stop finished strictly before every create started.
        stop_done_positions = [i for i, entry in enumerate(call_order) if entry.startswith("stop_")]
        create_start_positions = [i for i, entry in enumerate(call_order) if entry.startswith("create_")]
        assert stop_done_positions
        assert create_start_positions
        assert max(stop_done_positions) < min(create_start_positions), call_order

        # Sanity: the new "beta" came out of the reload fully usable — it can register a listener under
        # the now-uncontested "beta" owner_id. The ordering assertions above are what actually prove the
        # race is closed; this just confirms the flow doesn't leave the replacement in a broken state.
        beta_after = lifecycle.registry.get(app_key, "beta")
        assert beta_after is not None
        assert beta_after is not beta_before
        assert beta_after.unique_name == "beta"

        sub = await beta_after.bus.on(topic="test.race_topic", handler=noop, name="post_reload_listener")
        owner_listeners = lifecycle.hassette.bus_service.get_listeners_by_owner("beta")
        assert sub.listener.listener_id in {listener.listener_id for listener in owner_listeners}
