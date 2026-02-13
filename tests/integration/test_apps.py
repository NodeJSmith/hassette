import asyncio
import contextlib
import typing
from copy import deepcopy
from unittest.mock import patch

import pytest

from hassette import Hassette
from hassette.bus import Listener
from hassette.core.app_change_detector import ChangeSet
from hassette.types import Topic
from hassette.utils.app_utils import load_app_class_from_manifest

if typing.TYPE_CHECKING:
    from data.my_app import MyApp

    from hassette.core.app_handler import AppHandler


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
        """Verify that calling handle_changes() without config modifications preserves all running apps."""

        orig_apps = set(self.app_handler.apps.keys())

        event = asyncio.Event()
        results = []

        async def handler(**kwargs):
            results.append(kwargs)
            self.hassette.task_bucket.post_to_loop(event.set)

        self.hassette._bus_service.add_listener(
            Listener.create(
                self.app_handler.task_bucket,
                owner="test",
                topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
                handler=handler,
                where=None,
            )
        )

        # Drain any pending APP_LOAD_COMPLETED from bootstrap_apps().
        # On Python 3.12, the BusService may not have dispatched this event yet.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.5)
        results.clear()
        event.clear()

        await self.app_handler.handle_change_event()

        # will timeout, because we dont fire since there are no changes
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.2)
        assert not results, f"No events should have been fired, but got: {results}"

        new_apps = set(self.app_handler.apps.keys())
        assert orig_apps == new_apps, "No apps should be lost during handle_changes"

    async def test_handle_changes_disables_app(self) -> None:
        """Verify that editing hassette.toml to disable an app stops the running instance."""

        assert "my_app" in self.app_handler.apps, "Precondition: my_app starts enabled"
        assert self.app_handler.registry.manifests["my_app"].enabled is True, (
            "Precondition: my_app config shows enabled"
        )

        event = asyncio.Event()

        async def handler(**kwargs):  # noqa
            self.hassette.task_bucket.post_to_loop(event.set)

        self.hassette._bus_service.add_listener(
            Listener.create(
                self.app_handler.task_bucket,
                owner="test",
                topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
                handler=handler,
                where=None,
            )
        )

        with patch.object(self.app_handler.change_detector, "detect_changes") as mock_detect:
            mock_detect.return_value = ChangeSet(
                orphans=frozenset({"my_app"}),
                new_apps=frozenset(),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )

            await self.app_handler.handle_change_event()
            await asyncio.wait_for(event.wait(), timeout=1)

            assert "my_app" not in self.app_handler.apps, "my_app should stop after being disabled"
            assert "my_app_sync" in self.app_handler.apps, "Other enabled apps should continue running"

    async def test_handle_changes_enables_app(self) -> None:
        """Verify that editing hassette.toml to enable a disabled app starts the instance."""

        assert "disabled_app" not in self.app_handler.apps, "Precondition: disabled_app starts disabled"
        assert self.app_handler.registry.manifests["disabled_app"].enabled is False, (
            "Precondition: disabled_app config shows disabled"
        )

        new_app_config = deepcopy(self.app_handler.registry.manifests)
        new_app_config["disabled_app"].enabled = True

        event = asyncio.Event()

        async def handler(**kwargs):  # noqa
            self.hassette.task_bucket.post_to_loop(event.set)

        self.hassette._bus_service.add_listener(
            Listener.create(
                self.app_handler.task_bucket,
                owner="test",
                topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
                handler=handler,
                where=None,
            )
        )

        with (
            patch.object(self.app_handler.change_detector, "detect_changes") as mock_detect,
            patch.object(self.app_handler, "refresh_config") as mock_refresh_config,
        ):
            self.app_handler.registry.set_manifests(new_app_config)
            mock_refresh_config.return_value = (self.app_handler.registry.manifests, new_app_config)
            mock_detect.return_value = ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset({"disabled_app"}),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )

            await self.app_handler.handle_change_event()
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

        self.app_handler.registry.manifests["my_app"].app_config = {"test_entity": "light.office"}

        change_set = ChangeSet(
            orphans=frozenset(), new_apps=frozenset(), reimport_apps=frozenset(), reload_apps=frozenset({"my_app"})
        )

        await self.app_handler.apply_changes(change_set)
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
