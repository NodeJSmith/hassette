"""Forced reloads through the real lifecycle, registry and loader, on an app file a test edits (spec 161)."""

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_lifecycle_common import AppAdmissionMode
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry
from tests.support.app_staging_helpers import clear_app_modules
from tests.support.helpers import write_app

if TYPE_CHECKING:
    from hassette.app.app import App
    from hassette.app.app_config import AppConfig
    from hassette.testing import HassetteHarness

SHARED_FILE_SOURCE = """
from hassette import App

VALUE = {value}


class SharedFirstApp(App):
    pass


class SharedSecondApp(App):
    pass
"""

WAIT = AppAdmissionMode.WAIT_FOR_RELEASE


@pytest.fixture
def app_registry() -> AppRegistry:
    return AppRegistry()


@pytest.fixture
async def app_lifecycle(
    hassette_with_app_handler: "HassetteHarness", app_registry: AppRegistry
) -> AsyncIterator[AppLifecycleService]:
    lifecycle = AppLifecycleService(hassette_with_app_handler.hassette, parent=None, registry=app_registry)
    yield lifecycle
    await lifecycle.shutdown_all()


@pytest.fixture(autouse=True)
def clear_cache():
    clear_app_modules()
    yield
    clear_app_modules()


def get_app(registry: AppRegistry, key: str, instance_name: str) -> "App[AppConfig]":
    """The named running instance of ``key``."""
    app = registry.get(key, instance_name)
    assert app is not None, f"expected app {key!r}[{instance_name}] to be registered"
    return app


def shared_file_manifest(module_path: Path, app_key: str, class_name: str, names: list[str]) -> AppManifest:
    """A manifest for ``class_name`` in a file outside ``tests/data/apps``, with one instance per name."""
    return AppManifest(
        app_key=app_key,
        filename=module_path.name,
        class_name=class_name,
        app_dir=module_path.parent,
        app_config=[{"instance_name": name} for name in names],
        enabled=True,
        display_name=class_name,
        full_path=module_path,
    )


def module_value(app: "App[AppConfig]") -> int:
    """The ``VALUE`` of the module the app's class came from."""
    return sys.modules[type(app).__module__].VALUE


class TestReloadThroughTheLifecycle:
    @pytest.fixture
    def shared_file(self, tmp_path: Path) -> Path:
        # A unique module name: the loader files temp dirs under the apps package the harness config names.
        return write_app(tmp_path, f"shared_{os.urandom(4).hex()}.py", SHARED_FILE_SOURCE.format(value=1))

    async def test_reload_app_after_an_edit_runs_the_new_code(
        self, app_lifecycle: AppLifecycleService, app_registry: AppRegistry, shared_file: Path
    ) -> None:
        manifest = shared_file_manifest(shared_file, "shared_a", "SharedFirstApp", ["alpha"])
        app_registry.set_manifests({"shared_a": manifest})
        await app_lifecycle.start_app("shared_a", admission_mode=WAIT)
        write_app(shared_file.parent, shared_file.name, SHARED_FILE_SOURCE.format(value=22))

        await app_lifecycle.reload_app("shared_a", force_reload=True, admission_mode=WAIT)

        assert module_value(get_app(app_registry, "shared_a", "alpha")) == 22

    async def test_reload_instance_with_a_live_sibling_keeps_the_siblings_class(
        self, app_lifecycle: AppLifecycleService, app_registry: AppRegistry, shared_file: Path
    ) -> None:
        manifest = shared_file_manifest(shared_file, "shared_a", "SharedFirstApp", ["alpha", "beta"])
        app_registry.set_manifests({"shared_a": manifest})
        await app_lifecycle.start_app("shared_a", admission_mode=WAIT)
        alpha = get_app(app_registry, "shared_a", "alpha")
        write_app(shared_file.parent, shared_file.name, SHARED_FILE_SOURCE.format(value=22))

        await app_lifecycle.reload_instance("shared_a", "beta", force_reload=True, admission_mode=WAIT)

        beta = get_app(app_registry, "shared_a", "beta")
        assert type(beta) is type(alpha)
        assert module_value(beta) == 1

    async def test_sibling_key_reload_does_not_split_a_running_key(
        self, app_lifecycle: AppLifecycleService, app_registry: AppRegistry, shared_file: Path
    ) -> None:
        """Keys A and B share a file; reloading A after an edit leaves a new B instance on B's running class."""
        manifest_a = shared_file_manifest(shared_file, "shared_a", "SharedFirstApp", ["alpha"])
        manifest_b = shared_file_manifest(shared_file, "shared_b", "SharedSecondApp", ["one", "two"])
        app_registry.set_manifests({"shared_a": manifest_a, "shared_b": manifest_b})
        await app_lifecycle.start_app("shared_a", admission_mode=WAIT)
        await app_lifecycle.start_app("shared_b", admission_mode=WAIT)
        await app_lifecycle.stop_instance("shared_b", "two")
        b_one = get_app(app_registry, "shared_b", "one")
        write_app(shared_file.parent, shared_file.name, SHARED_FILE_SOURCE.format(value=22))

        await app_lifecycle.reload_app("shared_a", force_reload=True, admission_mode=WAIT)
        await app_lifecycle.start_instance("shared_b", "two", admission_mode=WAIT)

        assert module_value(get_app(app_registry, "shared_a", "alpha")) == 22
        assert type(get_app(app_registry, "shared_b", "two")) is type(b_one)

    async def test_a_live_instance_of_a_renamed_class_does_not_supply_the_class(
        self, app_lifecycle: AppLifecycleService, app_registry: AppRegistry, shared_file: Path
    ) -> None:
        """An instance left running across a class rename keeps its class; a new instance gets the new one."""
        app_registry.set_manifests(
            {"shared_a": shared_file_manifest(shared_file, "shared_a", "SharedFirstApp", ["alpha"])}
        )
        await app_lifecycle.start_app("shared_a", admission_mode=WAIT)
        renamed = shared_file_manifest(shared_file, "shared_a", "SharedSecondApp", ["alpha", "beta"])
        app_registry.set_manifests({"shared_a": renamed})

        await app_lifecycle.start_instance("shared_a", "beta", admission_mode=WAIT)

        assert type(get_app(app_registry, "shared_a", "beta")).__name__ == "SharedSecondApp"
