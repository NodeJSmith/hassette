"""Integration tests for hot reload via the app handler pipeline.

These tests bypass the real FileWatcherService and instead emit
HassetteFileWatcherEvent directly, eliminating filesystem-watcher
timing flakiness while still exercising the full change-detection
and app-lifecycle pipeline.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest

from hassette import Bus, Hassette
from hassette.events.hassette import HassetteFileWatcherEvent
from hassette.test_utils.helpers import create_app_manifest, write_app_toml, write_test_app_with_decorator
from hassette.types import ResourceStatus

if TYPE_CHECKING:
    from hassette.core.app_handler import AppHandler


async def emit_file_change_event(hassette: Hassette, changed_paths: set[Path]) -> None:
    """Emit a synthetic file-watcher event for the given paths."""
    event = HassetteFileWatcherEvent.create_event(changed_file_paths=changed_paths)
    await hassette.send_event(event.topic, event)


def wire_up_app_state_listener(bus: Bus, event: asyncio.Event, app_key: str, status: ResourceStatus):
    """Wire up a listener that fires when a specific app reaches the given status."""

    async def handler():
        bus.task_bucket.post_to_loop(event.set)

    bus.on_app_state_changed(handler=handler, app_key=app_key, status=status, once=True)


def wire_up_app_running_listener(bus: Bus, event: asyncio.Event, app_key: str):
    """Wire up a listener that fires when a specific app reaches RUNNING status."""
    wire_up_app_state_listener(bus, event, app_key, ResourceStatus.RUNNING)


@pytest.fixture
def hassette_and_handler(hassette_with_app_handler_custom_config: Hassette) -> tuple[Hassette, "AppHandler"]:
    """Extract Hassette + AppHandler pair from the custom-config fixture."""
    return hassette_with_app_handler_custom_config, hassette_with_app_handler_custom_config._app_handler


class TestBasicHotReload:
    """Basic hot reload functionality tests."""

    hassette: Hassette
    app_handler: "AppHandler"

    @pytest.fixture(autouse=True)
    def setup(self, hassette_and_handler: tuple[Hassette, "AppHandler"]):
        self.hassette, self.app_handler = hassette_and_handler

    async def test_hot_reload_starts_newly_enabled_app(self):
        """Enable a disabled app and verify it starts."""
        app_dir = self.hassette.config.app_dir
        toml_file = list(self.hassette.config.toml_files)[0]

        app1 = create_app_manifest(suffix="enabled", app_dir=app_dir, enabled=True)
        write_test_app_with_decorator(app_file=app1.full_path, class_name=app1.class_name)

        app_running_event = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, app_running_event, app1.app_key)

        write_app_toml(toml_file, app_dir=app_dir, apps=[app1])
        await emit_file_change_event(self.hassette, {toml_file, app1.full_path})

        with anyio.fail_after(3):
            await app_running_event.wait()

        snapshot = self.hassette._app_handler.registry.get_snapshot()
        assert self.hassette._app_handler.registry.get(app1.app_key, 0) is not None, f"Registry snapshot: {snapshot}"

    async def test_hot_reload_stops_newly_disabled_app(self):
        """Disable an enabled app via config change and verify it stops."""
        app_dir = self.hassette.config.app_dir
        toml_file = list(self.hassette.config.toml_files)[0]

        # Start an app
        app1 = create_app_manifest(suffix="stoppable", app_dir=app_dir, enabled=True)
        write_test_app_with_decorator(app_file=app1.full_path, class_name=app1.class_name)

        app_running = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, app_running, app1.app_key)

        write_app_toml(toml_file, app_dir=app_dir, apps=[app1])
        await emit_file_change_event(self.hassette, {toml_file, app1.full_path})

        with anyio.fail_after(3):
            await app_running.wait()

        app = self.app_handler.registry.get(app1.app_key, 0)
        assert app is not None

        # Disable by removing from config
        app_stopped = asyncio.Event()
        wire_up_app_state_listener(self.hassette._bus, app_stopped, app1.app_key, ResourceStatus.STOPPED)

        write_app_toml(toml_file, app_dir=app_dir, apps=[])
        await emit_file_change_event(self.hassette, {toml_file})

        with anyio.fail_after(3):
            await app_stopped.wait()

        assert self.app_handler.registry.get(app1.app_key, 0) is None

    async def test_hot_reload_reloads_app_with_config_change(self):
        """Change app config value and verify app is reloaded with new config."""
        app_dir = self.hassette.config.app_dir
        toml_file = list(self.hassette.config.toml_files)[0]

        # Start app with initial config
        app1 = create_app_manifest(
            suffix="cfgtest", app_dir=app_dir, enabled=True, app_config={"test_value": "initial"}
        )
        write_test_app_with_decorator(
            app_file=app1.full_path, class_name=app1.class_name, config_fields={"test_value": "str"}
        )

        app_running = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, app_running, app1.app_key)

        write_app_toml(toml_file, app_dir=app_dir, apps=[app1])
        await emit_file_change_event(self.hassette, {toml_file, app1.full_path})

        with anyio.fail_after(3):
            await app_running.wait()

        inst = self.app_handler.registry.get(app1.app_key, 0)
        assert inst is not None
        assert inst.app_config.test_value == "initial", f"Expected 'initial', got {inst.app_config.test_value}"

        # Change config value and wait for reload
        app1_updated = create_app_manifest(
            suffix="cfgtest", app_dir=app_dir, enabled=True, app_config={"test_value": "updated"}
        )

        app_running2 = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, app_running2, app1.app_key)

        write_app_toml(toml_file, app_dir=app_dir, apps=[app1_updated])
        await emit_file_change_event(self.hassette, {toml_file})

        with anyio.fail_after(3):
            await app_running2.wait()

        inst = self.app_handler.registry.get(app1.app_key, 0)
        assert inst is not None
        assert inst.app_config.test_value == "updated", f"Expected 'updated', got {inst.app_config.test_value}"

    async def test_hot_reload_reimports_app_when_file_changes(self):
        """Modify app Python file and verify app is reimported."""
        app_dir = self.hassette.config.app_dir
        toml_file = list(self.hassette.config.toml_files)[0]

        app1 = create_app_manifest(suffix="reimport", app_dir=app_dir, enabled=True)
        write_test_app_with_decorator(app_file=app1.full_path, class_name=app1.class_name)

        app_running = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, app_running, app1.app_key)

        write_app_toml(toml_file, app_dir=app_dir, apps=[app1])
        await emit_file_change_event(self.hassette, {toml_file, app1.full_path})

        with anyio.fail_after(3):
            await app_running.wait()

        inst = self.app_handler.registry.get(app1.app_key, 0)
        assert inst is not None
        original_class = inst.__class__

        # Rewrite the Python file with different content
        write_test_app_with_decorator(
            app_file=app1.full_path, class_name=app1.class_name, config_fields={"marker": "str | None"}
        )

        app_running2 = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, app_running2, app1.app_key)

        await emit_file_change_event(self.hassette, {app1.full_path})

        with anyio.fail_after(3):
            await app_running2.wait()

        inst = self.app_handler.registry.get(app1.app_key, 0)
        assert inst is not None
        # The class should be a new object after reimport
        assert inst.__class__ is not original_class


class TestOnlyAppDecorator:
    """Tests for @only_app decorator hot reload behavior."""

    hassette: Hassette
    app_handler: "AppHandler"

    @pytest.fixture(autouse=True)
    def setup(self, hassette_and_handler: tuple[Hassette, "AppHandler"]):
        self.hassette, self.app_handler = hassette_and_handler

    async def test_hot_reload_adds_only_app_decorator(self):
        """Add @only_app app to config and verify other apps stop."""
        app_dir = self.hassette.config.app_dir
        toml_file = list(self.hassette.config.toml_files)[0]

        # Start two normal apps
        app1 = create_app_manifest(suffix="normal1", app_dir=app_dir)
        app2 = create_app_manifest(suffix="normal2", app_dir=app_dir)
        write_test_app_with_decorator(app_file=app1.full_path, class_name=app1.class_name)
        write_test_app_with_decorator(app_file=app2.full_path, class_name=app2.class_name)

        app1_running = asyncio.Event()
        app2_running = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, app1_running, app1.app_key)
        wire_up_app_running_listener(self.hassette._bus, app2_running, app2.app_key)

        write_app_toml(toml_file, app_dir=app_dir, apps=[app1, app2])
        await emit_file_change_event(self.hassette, {toml_file, app1.full_path, app2.full_path})

        with anyio.fail_after(3):
            await app1_running.wait()
            await app2_running.wait()

        assert self.app_handler.registry.get(app1.app_key, 0) is not None
        assert self.app_handler.registry.get(app2.app_key, 0) is not None
        assert self.app_handler.registry.only_app is None

        # Add a third app with @only_app - existing apps should become orphans
        app3 = create_app_manifest(suffix="onlyapp", app_dir=app_dir)
        write_test_app_with_decorator(app_file=app3.full_path, class_name=app3.class_name, has_only_app=True)

        app3_running = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, app3_running, app3.app_key)

        write_app_toml(toml_file, app_dir=app_dir, apps=[app1, app2, app3])
        await emit_file_change_event(self.hassette, {toml_file, app3.full_path})

        with anyio.fail_after(3):
            await app3_running.wait()

        assert self.app_handler.registry.get(app1.app_key, 0) is None
        assert self.app_handler.registry.get(app2.app_key, 0) is None
        assert self.app_handler.registry.get(app3.app_key, 0) is not None
        assert self.app_handler.registry.only_app == app3.app_key

    async def test_only_app_persists_across_config_changes(self):
        """Verify @only_app filter persists when config values change."""
        app_dir = self.hassette.config.app_dir
        toml_file = list(self.hassette.config.toml_files)[0]

        only = create_app_manifest(suffix="persist", app_dir=app_dir, app_config={"test_value": "initial"})
        normal = create_app_manifest(suffix="filtered", app_dir=app_dir)
        write_test_app_with_decorator(
            app_file=only.full_path,
            class_name=only.class_name,
            has_only_app=True,
            config_fields={"test_value": "str"},
        )
        write_test_app_with_decorator(app_file=normal.full_path, class_name=normal.class_name)

        only_running = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, only_running, only.app_key)

        write_app_toml(toml_file, app_dir=app_dir, apps=[only, normal])
        await emit_file_change_event(self.hassette, {toml_file, only.full_path, normal.full_path})

        with anyio.fail_after(3):
            await only_running.wait()

        assert self.app_handler.registry.get(only.app_key, 0) is not None
        assert self.app_handler.registry.get(normal.app_key, 0) is None
        assert self.app_handler.registry.only_app == only.app_key

        # Change config value - only_app should reload with new config
        only_updated = create_app_manifest(suffix="persist", app_dir=app_dir, app_config={"test_value": "updated"})

        only_running2 = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, only_running2, only.app_key)

        write_app_toml(toml_file, app_dir=app_dir, apps=[only_updated, normal])
        await emit_file_change_event(self.hassette, {toml_file})

        with anyio.fail_after(3):
            await only_running2.wait()

        inst = self.app_handler.registry.get(only.app_key, 0)
        assert inst is not None
        assert inst.app_config.test_value == "updated"
        assert self.app_handler.registry.get(normal.app_key, 0) is None
        assert self.app_handler.registry.only_app == only.app_key

    async def test_removing_only_app_starts_previously_blocked_apps(self):
        """Remove @only_app decorator and verify previously-blocked apps start."""
        app_dir = self.hassette.config.app_dir
        toml_file = list(self.hassette.config.toml_files)[0]

        # Start two apps, one with @only_app — the other should be blocked
        only = create_app_manifest(suffix="onlyremove", app_dir=app_dir)
        blocked = create_app_manifest(suffix="wasblocked", app_dir=app_dir)
        write_test_app_with_decorator(app_file=only.full_path, class_name=only.class_name, has_only_app=True)
        write_test_app_with_decorator(app_file=blocked.full_path, class_name=blocked.class_name)

        only_running = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, only_running, only.app_key)

        write_app_toml(toml_file, app_dir=app_dir, apps=[only, blocked])
        await emit_file_change_event(self.hassette, {toml_file, only.full_path, blocked.full_path})

        with anyio.fail_after(3):
            await only_running.wait()

        assert self.app_handler.registry.get(only.app_key, 0) is not None
        assert self.app_handler.registry.get(blocked.app_key, 0) is None
        assert self.app_handler.registry.only_app == only.app_key

        # Rewrite the only_app's file WITHOUT @only_app decorator
        write_test_app_with_decorator(app_file=only.full_path, class_name=only.class_name, has_only_app=False)

        only_running2 = asyncio.Event()
        blocked_running = asyncio.Event()
        wire_up_app_running_listener(self.hassette._bus, only_running2, only.app_key)
        wire_up_app_running_listener(self.hassette._bus, blocked_running, blocked.app_key)

        await emit_file_change_event(self.hassette, {only.full_path})

        with anyio.fail_after(3):
            await only_running2.wait()
            await blocked_running.wait()

        # Both apps should now be running
        assert self.app_handler.registry.get(only.app_key, 0) is not None
        assert self.app_handler.registry.get(blocked.app_key, 0) is not None
        assert self.app_handler.registry.only_app is None
