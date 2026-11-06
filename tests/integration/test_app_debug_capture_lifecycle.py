"""Debug capture through the real app build, stop and change paths (spec 148 D6, D7, D8)."""

import asyncio
import contextlib
import logging
import sys
import typing
from types import ModuleType

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_handler import AppHandler
from hassette.core.app_registry import listed_apps, overlay_runtime_state
from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult
from hassette.schemas.app_snapshots import AppFullSnapshot, tally_app_statuses
from hassette.testing import HassetteHarness
from hassette.utils.app_utils import load_app_class_from_manifest
from hassette.web.mappers import app_list_response_from
from tests.support.app_manifests import make_test_app_manifest
from tests.support.factories import make_change_set
from tests.support.web_manifest_helpers import make_manifest_db_row

GATED_KEY = "gated_init"
MULTI_KEY = "multi_instance"


def multi_manifest(app_config: list[dict]) -> AppManifest:
    """The ``multi_instance`` test app's manifest with ``app_config``."""
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


async def test_starting_an_app_prunes_a_captured_name_outside_its_config(handler: AppHandler) -> None:
    """D8: a pair under a name no config block or running instance holds is dropped at the app's next start."""
    handler.lifecycle.set_apps_configs({MULTI_KEY: multi_manifest([{"instance_name": "alpha"}])})
    handler.registry.set_debug_capture(MULTI_KEY, ["alpha", "gone"], enabled=True)

    await handler.lifecycle.start_app(MULTI_KEY)

    assert handler.registry.debug_captured_names(MULTI_KEY) == {"alpha"}


async def stop_left_running(_app_key: str) -> None:
    """A stop that returns but fails to remove the instance."""


async def stop_cancelled(_app_key: str) -> typing.NoReturn:
    """A stop cancelled partway."""
    raise asyncio.CancelledError


@pytest.mark.parametrize("stop", [stop_left_running, stop_cancelled], ids=["left_running", "cancelled"])
async def test_removed_app_capture_ends_even_when_its_stop_does_not_finish(
    handler: AppHandler,
    monkeypatch: pytest.MonkeyPatch,
    stop: typing.Callable[[str], typing.Awaitable[None]],
) -> None:
    """D8: a removed app's routes answer 404, so neither a stop that leaves an instance running nor a cancelled stop
    may strand its capture.
    """
    handler.lifecycle.set_apps_configs({MULTI_KEY: multi_manifest([{"instance_name": "alpha"}])})
    await handler.lifecycle.start_app(MULTI_KEY)
    handler.set_debug_capture(MULTI_KEY, None, enabled=True)
    survivor = handler.registry.get(MULTI_KEY, "alpha")
    assert survivor is not None
    monkeypatch.setattr(handler.lifecycle, "stop_app", stop)

    # The orphan loop runs first and reads neither config, so empty ones are enough.
    with contextlib.suppress(asyncio.CancelledError):
        await handler.lifecycle.apply_changes(make_change_set(orphans={MULTI_KEY}), {}, {})

    assert handler.registry.debug_captured_names(MULTI_KEY) == set()
    assert survivor.debug_capture is False
    assert survivor.logger.level > logging.DEBUG


async def test_a_stop_that_leaves_work_running_returns_the_instance_loggers_to_config(
    handler: AppHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An instance whose stop is not restart-safe leaves the registry, so ``off`` can't reach it afterwards; its
    loggers, which outlive it, go back to their config levels at the stop, while the pair stays for its next start.
    """
    handler.lifecycle.set_apps_configs({MULTI_KEY: multi_manifest([{"instance_name": "alpha"}])})
    await handler.lifecycle.start_app(MULTI_KEY)
    handler.set_debug_capture(MULTI_KEY, None, enabled=True)
    app = handler.registry.get(MULTI_KEY, "alpha")
    assert app is not None
    assert app.logger.level == logging.DEBUG
    real_shutdown = app.shutdown

    async def shutdown_left_running() -> ShutdownOutcome:
        await real_shutdown()
        return ShutdownOutcome(ShutdownResult.INCOMPLETE, ("app-worker",), "test: work left running")

    monkeypatch.setattr(app, "shutdown", shutdown_left_running)

    await handler.lifecycle.stop_instance(MULTI_KEY, "alpha")

    assert handler.registry.get(MULTI_KEY, "alpha") is None
    assert app.debug_capture is False
    assert app.logger.level > logging.DEBUG
    assert app.bus.logger.level > logging.DEBUG
    assert app.lifecycle_logger.level > logging.DEBUG
    assert handler.registry.debug_captured_names(MULTI_KEY) == {"alpha"}


async def test_app_list_reports_capture_for_each_instance(handler: AppHandler) -> None:
    """``GET /api/apps``'s path from a real registry, DB rows overlaid with runtime state, reports each instance's own
    capture.
    """
    handler.lifecycle.set_apps_configs(
        {MULTI_KEY: multi_manifest([{"instance_name": "alpha"}, {"instance_name": "beta"}])}
    )
    await handler.lifecycle.start_app(MULTI_KEY)
    handler.set_debug_capture(MULTI_KEY, "alpha", enabled=True)

    infos = listed_apps(overlay_runtime_state([make_manifest_db_row(MULTI_KEY)], handler.registry))
    response = app_list_response_from(
        AppFullSnapshot(manifests=tuple(infos), total=len(infos), status_counts=tally_app_statuses(infos))
    )

    (summary,) = response.apps
    assert {i.instance_name: i.debug_capture for i in summary.instances} == {"alpha": True, "beta": False}
