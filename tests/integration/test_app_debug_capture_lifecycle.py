"""Debug capture through the real app build, stop and change paths (spec 148 D6, D7, D8)."""

import asyncio
import logging
import sys
import typing
from types import ModuleType

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_handler import AppHandler
from hassette.testing import HassetteHarness
from hassette.utils.app_utils import load_app_class_from_manifest
from tests.support.factories import make_change_set, make_test_app_manifest

GATED_KEY = "gated_init"
MULTI_KEY = "multi_instance"


def multi_manifest(app_config: list[dict]) -> AppManifest:
    return make_test_app_manifest(MULTI_KEY, "multi_instance_app.py", "MultiInstanceApp", app_config)


def load_gated_module(handler: AppHandler, manifest: AppManifest) -> ModuleType:
    """Load the gated app the way the factory will, and reset its events.

    The loader imports app modules under its own package name and caches the class, so the test reaches the module
    the running app will use through the loaded class, not through a plain import.
    """
    app_class = load_app_class_from_manifest(manifest, config=handler.hassette.config)
    module = sys.modules[app_class.__module__]
    module.reset()
    return module


@pytest.fixture
async def handler(hassette_with_app_handler: HassetteHarness) -> typing.AsyncIterator[AppHandler]:
    """A fresh AppHandler with its own registry, so apps started here never show up in the module harness's.

    Only one harness may hold the process-global Hassette context, so this reuses the harness's Hassette.
    """
    app_handler = AppHandler(hassette_with_app_handler.hassette, parent=None)
    try:
        yield app_handler
    finally:
        await app_handler.lifecycle.shutdown_all()


async def test_toggle_reaches_an_app_mid_startup_and_survives_its_reload(handler: AppHandler) -> None:
    """The toggle takes no lock, so it applies to an instance still in on_initialize, and a reload keeps it."""
    manifest = make_test_app_manifest(GATED_KEY, "gated_init_app.py", "GatedInitApp", [{"instance_name": "alpha"}])
    gated = load_gated_module(handler, manifest)
    handler.lifecycle.set_apps_configs({GATED_KEY: manifest})
    start = asyncio.create_task(handler.lifecycle.start_app(GATED_KEY))
    try:
        await asyncio.wait_for(gated.ENTERED.wait(), timeout=3)
        app = handler.registry.get(GATED_KEY, "alpha")
        assert app is not None
        assert not start.done(), "startup is still blocked in on_initialize"

        handler.set_debug_capture(GATED_KEY, "alpha", enabled=True)

        assert app.logger.level == logging.DEBUG
        assert app.bus.logger.level == logging.DEBUG
        assert app.lifecycle_logger.level == logging.DEBUG
    finally:
        gated.GATE.set()
        await asyncio.wait_for(start, timeout=5)

    await asyncio.wait_for(handler.lifecycle.reload_instance(GATED_KEY, "alpha"), timeout=5)

    reloaded = handler.registry.get(GATED_KEY, "alpha")
    assert reloaded is not None
    assert reloaded is not app
    assert reloaded.debug_capture is True
    assert reloaded.logger.level == logging.DEBUG
    assert reloaded.bus.logger.level == logging.DEBUG


async def test_stopping_a_running_orphan_ends_its_capture(handler: AppHandler) -> None:
    """D8: a stop of an instance whose name left the config drops its pair, so nothing invisible is left."""
    handler.lifecycle.set_apps_configs(
        {MULTI_KEY: multi_manifest([{"instance_name": "alpha"}, {"instance_name": "beta"}])}
    )
    await handler.lifecycle.start_app(MULTI_KEY)
    handler.set_debug_capture(MULTI_KEY, None, enabled=True)
    # A config edit with no reload applied yet: beta leaves the config but keeps running, a running orphan.
    handler.registry.manifests[MULTI_KEY].app_config = [{"instance_name": "alpha"}]
    assert handler.registry.get(MULTI_KEY, "beta") is not None

    await handler.lifecycle.stop_instance(MULTI_KEY, "beta")

    assert handler.registry.debug_captured_names(MULTI_KEY) == {"alpha"}


async def test_removed_app_capture_is_cleared_even_when_its_stop_is_cancelled(
    handler: AppHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D8: the removed app's routes answer 404, so a cancelled stop must not strand its capture."""
    handler.lifecycle.set_apps_configs({MULTI_KEY: multi_manifest([{"instance_name": "alpha"}])})
    await handler.lifecycle.start_app(MULTI_KEY)
    handler.set_debug_capture(MULTI_KEY, None, enabled=True)
    survivor = handler.registry.get(MULTI_KEY, "alpha")
    assert survivor is not None

    async def cancelled_stop(_app_key: str) -> typing.NoReturn:
        raise asyncio.CancelledError

    monkeypatch.setattr(handler.lifecycle, "stop_app", cancelled_stop)

    # The orphan loop runs first and reads neither config, so empty ones are enough.
    with pytest.raises(asyncio.CancelledError):
        await handler.lifecycle.apply_changes(make_change_set(orphans={MULTI_KEY}), {}, {})

    assert handler.registry.debug_captured_names(MULTI_KEY) == set()
    assert survivor.debug_capture is False
    assert survivor.logger.level > logging.DEBUG
