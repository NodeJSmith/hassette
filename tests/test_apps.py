import asyncio
import typing
from copy import deepcopy
from unittest.mock import patch

import pytest

from hassette.bus import Listener
from hassette.core import Hassette
from hassette.services.app_handler import AppHandler, load_app_class_from_manifest
from hassette.types.topics import HASSETTE_EVENT_APP_LOAD_COMPLETED

if typing.TYPE_CHECKING:
    from data.my_app import MyApp


class TestApps:
    hassette: Hassette
    app_handler: "AppHandler"

    @pytest.fixture(autouse=True)
    def setup(self, hassette_with_app_handler: Hassette):
        self.hassette = hassette_with_app_handler
        self.app_handler = hassette_with_app_handler._app_handler

    async def test_apps_are_working(self) -> None:
        """Test actual WebSocket calls against running HA instance."""

        assert self.app_handler.apps, "There should be at least one app group"
        assert "my_app" in self.app_handler.apps, "my_app should be one of the app groups"
        assert "my_app_sync" in self.app_handler.apps, "my_app_sync should be one of the app groups"
        assert "disabled_app" not in self.app_handler.apps, "disabled_app should remain disabled"

        # test that an app that only has config values but no class_name/filename is ignored
        assert "myfakeapp" not in self.app_handler.apps, "myfakeapp should not be one of the app groups"

    def test_get_app_instance(self) -> None:
        """Test getting a specific app instance."""

        app = self.app_handler.get("my_app", 0)
        assert app is not None, "App instance should be found"

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
        """Verify that editing hassette.toml to disable an app stops the running instance."""

        orig_apps = set(self.app_handler.apps.keys())

        event = asyncio.Event()

        async def handler(*args, **kwargs):  # noqa
            self.hassette.task_bucket.post_to_loop(event.set)

        self.hassette._bus_service.add_listener(
            Listener.create(
                self.app_handler.task_bucket,
                owner="test",
                topic=HASSETTE_EVENT_APP_LOAD_COMPLETED,
                handler=handler,
                where=None,
            )
        )

        await self.app_handler.handle_changes()
        await asyncio.wait_for(event.wait(), timeout=1)

        new_apps = set(self.app_handler.apps.keys())
        assert orig_apps == new_apps, "No apps should be lost during handle_changes"

    async def test_handle_changes_disables_app(self) -> None:
        """Verify that editing hassette.toml to disable an app stops the running instance."""

        assert "my_app" in self.app_handler.apps, "Precondition: my_app starts enabled"
        assert self.app_handler.apps_config["my_app"].enabled is True, "Precondition: my_app config shows enabled"

        event = asyncio.Event()

        async def handler(*args, **kwargs):  # noqa
            self.hassette.task_bucket.post_to_loop(event.set)

        self.hassette._bus_service.add_listener(
            Listener.create(
                self.app_handler.task_bucket,
                owner="test",
                topic=HASSETTE_EVENT_APP_LOAD_COMPLETED,
                handler=handler,
                where=None,
            )
        )

        with patch.object(self.app_handler, "_calculate_app_changes") as mock_calc_changes:
            mock_calc_changes.return_value = (
                {"my_app"},  # orphans
                set(),  # new_apps
                set(),  # reimport_apps
                set(),  # reload_apps
            )

            await self.app_handler.handle_changes()
            await asyncio.wait_for(event.wait(), timeout=1)

            assert "my_app" not in self.app_handler.apps, "my_app should stop after being disabled"
            assert "my_app_sync" in self.app_handler.apps, "Other enabled apps should continue running"

    async def test_handle_changes_enables_app(self) -> None:
        """Verify that editing hassette.toml to enable a disabled app starts the instance."""

        assert "disabled_app" not in self.app_handler.apps, "Precondition: disabled_app starts disabled"
        assert self.app_handler.apps_config["disabled_app"].enabled is False, (
            "Precondition: disabled_app config shows disabled"
        )

        new_app_config = deepcopy(self.app_handler.apps_config)
        new_app_config["disabled_app"].enabled = True

        event = asyncio.Event()

        async def handler(*args, **kwargs):  # noqa
            self.hassette.task_bucket.post_to_loop(event.set)

        self.hassette._bus_service.add_listener(
            Listener.create(
                self.app_handler.task_bucket,
                owner="test",
                topic=HASSETTE_EVENT_APP_LOAD_COMPLETED,
                handler=handler,
                where=None,
            )
        )

        with (
            patch.object(self.app_handler, "_calculate_app_changes") as mock_calc_changes,
            patch.object(self.app_handler, "refresh_config") as mock_refresh_config,
        ):
            self.app_handler.apps_config = new_app_config
            mock_refresh_config.return_value = (self.app_handler.apps_config, new_app_config)
            mock_calc_changes.return_value = (
                set(),  # orphans
                {"disabled_app"},  # new_apps
                set(),  # reimport_apps
                set(),  # reload_apps
            )

            await self.app_handler.handle_changes()
            await asyncio.wait_for(event.wait(), timeout=1)

            assert "disabled_app" in self.app_handler.apps, "disabled_app should start after being enabled"
            assert "my_app" in self.app_handler.apps, "Other enabled apps should continue running"

    async def test_config_changes_are_reflected_after_reload(self) -> None:
        """Verify that editing hassette.toml to change an app's config reloads the instance."""

        assert "my_app" in self.app_handler.apps, "Precondition: my_app starts enabled"

        my_app_instance = typing.cast("MyApp", self.app_handler.get("my_app", 0))
        assert my_app_instance is not None, "Precondition: my_app instance should exist"

        assert my_app_instance.app_config.test_entity == "input_button.test", (
            "Precondition: my_app config has initial value"
        )

        self.app_handler.apps_config["my_app"].app_config = {"test_entity": "light.office"}

        await self.app_handler._reload_apps_due_to_config({"my_app"})
        # using manual sleep here, as the event doesn't get sent unless we call `handle_changes`
        await asyncio.sleep(0.3)

        assert "my_app" in self.app_handler.apps, "my_app should still be running after reload"
        my_app_instance = typing.cast("MyApp", self.app_handler.get("my_app", 0))
        assert my_app_instance is not None, "my_app instance should still exist after reload"
        assert my_app_instance.app_config.test_entity == "light.office", "my_app config should be updated after reload"

    async def test_app_with_instance_name(self) -> None:
        """Test that an app with a specific instance_name in config starts correctly."""

        assert "my_app" in self.app_handler.apps, "Precondition: my_app starts enabled"

        my_app_instance = self.app_handler.get("my_app", 0)
        assert my_app_instance is not None, "my_app instance should exist"
        assert my_app_instance.app_config.instance_name == "unique_instance_name", (
            "my_app instance should have the specified instance_name"
        )

    async def test_app_without_instance_name(self) -> None:
        """Test that an app without a specific instance_name in config starts with default naming."""

        assert "my_app_sync" in self.app_handler.apps, "Precondition: my_app_sync starts enabled"

        expected_name = "MyAppSync.0"

        my_app_sync_instance = self.app_handler.get("my_app_sync", 0)
        assert my_app_sync_instance is not None, "my_app_sync instance should exist"
        assert my_app_sync_instance.app_config.instance_name == expected_name, (
            f"my_app_sync instance should have the default instance_name {expected_name},"
            f" found {my_app_sync_instance.app_config.instance_name}"
        )
