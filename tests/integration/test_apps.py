import asyncio
import contextlib
import typing
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_change_detector import ChangeSet
from hassette.testing import HassetteHarness, wait_for
from hassette.types import Topic
from hassette.utils.app_utils import load_app_class_from_manifest
from tests.support.factories import make_change_set
from tests.support.helpers import create_listener

if typing.TYPE_CHECKING:
    from hassette.core.app_handler import AppHandler
    from tests.data.apps.my_app import MyApp


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

        my_app_instance = self.app_handler.get("my_app", instance_name="unique_instance_name")
        assert my_app_instance is not None, "my_app instance should exist"
        assert my_app_instance.app_config.instance_name == "unique_instance_name", (
            "my_app instance should have the specified instance_name"
        )

    async def test_app_instance_name_is_its_unique_name(self) -> None:
        """A configured app runs under exactly the instance_name its config sets, which is also its unique_name."""
        assert "my_app_sync" in self.app_handler.registry, "Precondition: my_app_sync starts enabled"

        instance = self.app_handler.get("my_app_sync", instance_name="my_app_sync")
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

    async def test_reload_does_not_carry_error_handlers_to_new_instance(self) -> None:
        """A reload builds a new app whose Bus and Scheduler don't inherit the old instance's error handlers."""
        old_app = self.app_handler.get("my_app")
        assert old_app is not None
        old_app.bus.on_error(AsyncMock())
        old_app.scheduler.on_error(AsyncMock())

        await self.app_handler.reload_app("my_app", force_reload=False)

        new_app = self.app_handler.get("my_app")
        assert new_app is not None
        assert new_app is not old_app
        assert new_app.bus._error_handler is None
        assert new_app.scheduler._error_handler is None
        assert old_app.bus._error_handler is None
        assert old_app.scheduler._error_handler is None

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
