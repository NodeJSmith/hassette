"""Integration tests for hot reload via the app handler pipeline.

These tests bypass the real FileWatcherService and instead emit
HassetteFileWatcherEvent directly, eliminating filesystem-watcher
timing flakiness while still exercising the full change-detection
and app-lifecycle pipeline.
"""

import asyncio
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest

from hassette.testing import HassetteHarness
from hassette.types import ResourceStatus
from tests.support.harness import preserve_config
from tests.support.helpers import (
    create_app_manifest,
    emit_file_change_event,
    wire_up_app_running_listener,
    wire_up_app_state_listener,
    write_app_toml,
    write_test_app_with_decorator,
)

if TYPE_CHECKING:
    from hassette.core.app_handler import AppHandler


@pytest.fixture
def hassette_and_handler(
    hassette_with_app_handler_custom_config: HassetteHarness,
) -> tuple[HassetteHarness, "AppHandler"]:
    """Extract HassetteHarness + AppHandler pair from the custom-config fixture.

    Wraps the session-scoped config in preserve_config so that reload() mutations
    from one test don't leak into the next test's starting state.
    """
    app_dir = hassette_with_app_handler_custom_config.config.apps.directory
    with preserve_config(hassette_with_app_handler_custom_config.config):
        yield hassette_with_app_handler_custom_config, hassette_with_app_handler_custom_config.app_handler
    for f in app_dir.iterdir():
        if f.is_file():
            f.unlink()
        elif f.is_dir() and f.name == "__pycache__":
            shutil.rmtree(f)


class TestBasicHotReload:
    """Basic hot reload functionality tests."""

    hassette: HassetteHarness
    app_handler: "AppHandler"
    app_dir: Path
    toml_file: Path

    @pytest.fixture(autouse=True)
    def setup(self, hassette_and_handler: tuple[HassetteHarness, "AppHandler"]):
        self.hassette, self.app_handler = hassette_and_handler
        self.app_dir = self.hassette.config.apps.directory
        self.toml_file = list(self.hassette.config.toml_files)[0]

    async def test_hot_reload_starts_newly_enabled_app(self):
        """Enable a disabled app and verify it starts."""
        app1 = create_app_manifest(suffix="enabled", app_dir=self.app_dir, enabled=True)
        write_test_app_with_decorator(app_file=app1.full_path, class_name=app1.class_name)

        app_running_event = asyncio.Event()
        await wire_up_app_running_listener(self.hassette.bus, app_running_event, app1.app_key)

        write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[app1])
        await emit_file_change_event(self.hassette, {self.toml_file, app1.full_path})

        with anyio.fail_after(3):
            await app_running_event.wait()

        snapshot = self.hassette.app_handler.registry.get_snapshot()
        assert self.hassette.app_handler.registry.get(app1.app_key, 0) is not None, f"Registry snapshot: {snapshot}"

    async def test_hot_reload_stops_newly_disabled_app(self):
        """Disable an enabled app via config change and verify it stops."""
        # Start an app
        app1 = create_app_manifest(suffix="stoppable", app_dir=self.app_dir, enabled=True)
        write_test_app_with_decorator(app_file=app1.full_path, class_name=app1.class_name)

        app_running = asyncio.Event()
        await wire_up_app_running_listener(self.hassette.bus, app_running, app1.app_key)

        write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[app1])
        await emit_file_change_event(self.hassette, {self.toml_file, app1.full_path})

        with anyio.fail_after(3):
            await app_running.wait()

        app = self.app_handler.registry.get(app1.app_key, 0)
        assert app is not None

        # Disable by removing from config
        app_stopped = asyncio.Event()
        await wire_up_app_state_listener(self.hassette.bus, app_stopped, app1.app_key, ResourceStatus.STOPPED)

        write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[])
        await emit_file_change_event(self.hassette, {self.toml_file})

        with anyio.fail_after(3):
            await app_stopped.wait()

        assert self.app_handler.registry.get(app1.app_key, 0) is None

    async def test_hot_reload_reloads_app_with_config_change(self):
        """Change app config value and verify app is reloaded with new config."""
        # Start app with initial config
        app1 = create_app_manifest(
            suffix="cfgtest", app_dir=self.app_dir, enabled=True, app_config={"test_value": "initial"}
        )
        write_test_app_with_decorator(
            app_file=app1.full_path, class_name=app1.class_name, config_fields={"test_value": "str"}
        )

        app_running = asyncio.Event()
        await wire_up_app_running_listener(self.hassette.bus, app_running, app1.app_key)

        write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[app1])
        await emit_file_change_event(self.hassette, {self.toml_file, app1.full_path})

        with anyio.fail_after(3):
            await app_running.wait()

        inst = self.app_handler.registry.get(app1.app_key, 0)
        assert inst is not None
        assert inst.app_config.test_value == "initial", f"Expected 'initial', got {inst.app_config.test_value}"

        # Change config value and wait for reload
        app1_updated = create_app_manifest(
            suffix="cfgtest", app_dir=self.app_dir, enabled=True, app_config={"test_value": "updated"}
        )

        app_running2 = asyncio.Event()
        await wire_up_app_running_listener(self.hassette.bus, app_running2, app1.app_key)

        write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[app1_updated])
        await emit_file_change_event(self.hassette, {self.toml_file})

        with anyio.fail_after(3):
            await app_running2.wait()

        inst = self.app_handler.registry.get(app1.app_key, 0)
        assert inst is not None
        assert inst.app_config.test_value == "updated", f"Expected 'updated', got {inst.app_config.test_value}"

    async def test_hot_reload_reimports_app_when_file_changes(self):
        """Modify app Python file and verify app is reimported."""
        app1 = create_app_manifest(suffix="reimport", app_dir=self.app_dir, enabled=True)
        write_test_app_with_decorator(app_file=app1.full_path, class_name=app1.class_name)

        app_running = asyncio.Event()
        await wire_up_app_running_listener(self.hassette.bus, app_running, app1.app_key)

        write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[app1])
        await emit_file_change_event(self.hassette, {self.toml_file, app1.full_path})

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
        await wire_up_app_running_listener(self.hassette.bus, app_running2, app1.app_key)

        await emit_file_change_event(self.hassette, {app1.full_path})

        with anyio.fail_after(3):
            await app_running2.wait()

        inst = self.app_handler.registry.get(app1.app_key, 0)
        assert inst is not None
        # The class should be a new object after reimport
        assert inst.__class__ is not original_class


class TestOnlyAppsConfigFilter:
    """Tests for the `hassette run --app` filter (config.only_apps) through the reload pipeline."""

    hassette: HassetteHarness
    app_handler: "AppHandler"
    app_dir: Path
    toml_file: Path

    @pytest.fixture(autouse=True)
    def setup(self, hassette_and_handler: tuple[HassetteHarness, "AppHandler"]):
        self.hassette, self.app_handler = hassette_and_handler
        self.app_dir = self.hassette.config.apps.directory
        self.toml_file = list(self.hassette.config.toml_files)[0]

    async def test_only_apps_starts_named_apps_and_blocks_the_rest(self, monkeypatch: pytest.MonkeyPatch):
        """With two keys in the filter, both named apps run and the third is blocked."""
        kept_a = create_app_manifest(suffix="kepta", app_dir=self.app_dir)
        kept_b = create_app_manifest(suffix="keptb", app_dir=self.app_dir)
        excluded = create_app_manifest(suffix="excluded", app_dir=self.app_dir)
        for manifest in (kept_a, kept_b, excluded):
            write_test_app_with_decorator(app_file=manifest.full_path, class_name=manifest.class_name)

        # HASSETTE__ONLY_APPS is the env-var form of `hassette run --app <a> --app <b>`; unlike a
        # direct attribute set, it survives the config.reload() inside handle_change_event.
        monkeypatch.setenv("HASSETTE__ONLY_APPS", json.dumps([kept_a.app_key, kept_b.app_key]))

        kept_a_running = asyncio.Event()
        kept_b_running = asyncio.Event()
        await wire_up_app_running_listener(self.hassette.bus, kept_a_running, kept_a.app_key)
        await wire_up_app_running_listener(self.hassette.bus, kept_b_running, kept_b.app_key)

        write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[kept_a, kept_b, excluded])
        await emit_file_change_event(
            self.hassette, {self.toml_file, kept_a.full_path, kept_b.full_path, excluded.full_path}
        )

        with anyio.fail_after(3):
            await kept_a_running.wait()
            await kept_b_running.wait()

        assert self.app_handler.registry.get(kept_a.app_key, 0) is not None
        assert self.app_handler.registry.get(kept_b.app_key, 0) is not None
        assert self.app_handler.registry.get(excluded.app_key, 0) is None
        assert self.app_handler.registry.only_apps == frozenset({kept_a.app_key, kept_b.app_key})

        snapshot = self.app_handler.registry.get_full_snapshot()
        statuses = {m.app_key: m.status for m in snapshot.manifests}
        assert statuses[excluded.app_key] == "blocked"
        assert snapshot.only_apps == sorted([kept_a.app_key, kept_b.app_key])
