"""System tests for app lifecycle — real apps loaded from disk with working resources."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from hassette import Hassette
from hassette.config.config import HassetteConfig
from hassette.testing import wait_for
from hassette.types.enums import ResourceStatus

from .conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system]

ENTITY = "light.kitchen_lights"
DOMAIN = "light"


def enable_autodetect(config: HassetteConfig, app_dir: Path) -> HassetteConfig:
    """Return a deep copy of config with app autodetection enabled and directory set."""
    config = config.model_copy(deep=True)
    config.apps.autodetect = True
    config.apps.directory = app_dir
    return config


def find_app(hassette, class_name: str):
    """Find an app instance by class name, with a clear error if missing."""
    keys = hassette.app_handler.registry.app_keys()
    key = next((k for k in keys if class_name in k), None)
    assert key is not None, f"{class_name} not found in app_handler registry: {keys}"
    return key, hassette.app_handler.get(key, 0)


@asynccontextmanager
async def start_with_inline_app(ha_container: str, tmp_path: Path, **modules: str) -> AsyncIterator[Hassette]:
    """Write inline app modules into the config's apps directory and start Hassette on them.

    Args:
        ha_container: Base URL of the running Home Assistant instance.
        tmp_path: Per-test temporary directory, passed through to ``make_system_config`` — which
            owns the apps directory, so callers never build or create that path themselves.
        **modules: Module stem mapped to its app source, written as ``<stem>.py``. Pass more than
            one to bring up several apps together.

    Yields:
        The running Hassette instance, with autodetection pointed at the apps directory.
    """
    config = make_system_config(ha_container, tmp_path)
    apps_dir = config.apps.directory
    for stem, source in modules.items():
        (apps_dir / f"{stem}.py").write_text(source)

    async with startup_context(enable_autodetect(config, apps_dir)) as hassette:
        yield hassette


async def test_trivial_app_initializes(ha_container: str, tmp_path: Path, system_app_dir: Path) -> None:
    """An app loaded from disk appears in the registry with RUNNING status after startup."""
    config = make_system_config(ha_container, tmp_path)
    config = enable_autodetect(config, system_app_dir)

    async with startup_context(config) as hassette:
        trivial_key, app_instance = find_app(hassette, "TrivialApp")
        assert len(hassette.app_handler.registry.get_running_apps(trivial_key)) >= 1
        assert app_instance.status == ResourceStatus.RUNNING


async def test_app_gets_working_api(ha_container: str, tmp_path: Path) -> None:
    """An app can call get_states() in on_initialize and receives real entity data."""
    app_code = """\
from hassette import App


class ApiCheckApp(App):
    async def on_initialize(self) -> None:
        self.fetched_states = await self.api.get_states()
"""

    async with start_with_inline_app(ha_container, tmp_path, api_check_app=app_code) as hassette:
        _, app_instance = find_app(hassette, "ApiCheckApp")
        assert app_instance.status == ResourceStatus.RUNNING

        fetched = app_instance.fetched_states  # pyright: ignore[reportAttributeAccessIssue]
        assert len(fetched) > 0


async def test_app_bus_handler_fires(ha_container: str, tmp_path: Path, system_app_dir: Path) -> None:
    """A bus handler registered in on_initialize receives real HA state-change events."""
    config = make_system_config(ha_container, tmp_path)
    config = enable_autodetect(config, system_app_dir)

    async with startup_context(config) as hassette:
        _, app_instance = find_app(hassette, "BusHandlerApp")
        assert app_instance.status == ResourceStatus.RUNNING

        # toggle_and_capture cannot be used here — the handler is registered by the app, not the test

        await hassette.api.call_service(DOMAIN, "toggle", {"entity_id": ENTITY})

        await wait_for(
            lambda: len(app_instance.captured_events) > 0,  # pyright: ignore[reportAttributeAccessIssue]
            timeout=15.0,
            desc="BusHandlerApp.captured_events to be non-empty",
        )

        assert len(app_instance.captured_events) > 0  # pyright: ignore[reportAttributeAccessIssue]


async def test_app_scheduler_fires(ha_container: str, tmp_path: Path) -> None:
    """An app can schedule a run_in job in on_initialize and the callback fires."""
    app_code = """\
from hassette import App


class SchedulerCheckApp(App):
    async def on_initialize(self) -> None:
        self.fired: list[int] = []
        await self.scheduler.run_in(self._callback, 1, name="scheduler_check_callback")

    async def _callback(self) -> None:
        self.fired.append(1)
"""

    async with start_with_inline_app(ha_container, tmp_path, scheduler_check_app=app_code) as hassette:
        _, app_instance = find_app(hassette, "SchedulerCheckApp")
        assert app_instance.status == ResourceStatus.RUNNING

        await wait_for(
            lambda: len(app_instance.fired) > 0,  # pyright: ignore[reportAttributeAccessIssue]
            timeout=5.0,
            desc="SchedulerCheckApp callback to fire",
        )


async def test_app_state_access(ha_container: str, tmp_path: Path) -> None:
    """An app can access light domain states via self.states.light in on_initialize."""
    app_code = """\
from hassette import App


class StateCheckApp(App):
    async def on_initialize(self) -> None:
        self.light_states = list(self.states.light.items())
"""

    async with start_with_inline_app(ha_container, tmp_path, state_check_app=app_code) as hassette:
        _, app_instance = find_app(hassette, "StateCheckApp")
        assert app_instance.status == ResourceStatus.RUNNING

        light_states = app_instance.light_states  # pyright: ignore[reportAttributeAccessIssue]
        assert len(light_states) > 0


async def test_app_shutdown_hook(ha_container: str, tmp_path: Path) -> None:
    """An app's on_shutdown hook is called when Hassette shuts down."""
    app_code = """\
from hassette import App


class ShutdownCheckApp(App):
    async def on_initialize(self) -> None:
        self.shutdown_called = False

    async def on_shutdown(self) -> None:
        self.shutdown_called = True
"""

    async with start_with_inline_app(ha_container, tmp_path, shutdown_check_app=app_code) as hassette:
        _, app_instance = find_app(hassette, "ShutdownCheckApp")

    # After startup_context exits, shutdown has completed
    assert app_instance.shutdown_called is True  # pyright: ignore[reportAttributeAccessIssue]


async def test_multiple_apps_isolation(ha_container: str, tmp_path: Path) -> None:
    """Two apps are isolated: events for one entity do not bleed into an unrelated app."""
    app_a_code = """\
from hassette import App
from hassette.events import RawStateChangeEvent


class IsolationAppA(App):
    async def on_initialize(self) -> None:
        self.captured: list[RawStateChangeEvent] = []
        await self.bus.on_state_change("light.kitchen_lights", handler=self._on_change, name="kitchen_lights")

    async def _on_change(self, event: RawStateChangeEvent) -> None:
        self.captured.append(event)
"""
    app_b_code = """\
from hassette import App


class IsolationAppB(App):
    async def on_initialize(self) -> None:
        self.captured: list[object] = []
"""

    async with start_with_inline_app(
        ha_container, tmp_path, isolation_app_a=app_a_code, isolation_app_b=app_b_code
    ) as hassette:
        _, app_a = find_app(hassette, "IsolationAppA")
        _, app_b = find_app(hassette, "IsolationAppB")
        assert app_a.status == ResourceStatus.RUNNING
        assert app_b.status == ResourceStatus.RUNNING

        # toggle_and_capture cannot be used here — the handler is registered by the app, not the test
        await hassette.api.call_service(DOMAIN, "toggle", {"entity_id": ENTITY})

        await wait_for(
            lambda: len(app_a.captured) >= 1,  # pyright: ignore[reportAttributeAccessIssue]
            timeout=15.0,
            desc="IsolationAppA.captured to receive at least one event",
        )

        # Wait a bit more to confirm AppB stays empty
        await asyncio.sleep(2)

        assert len(app_a.captured) >= 1  # pyright: ignore[reportAttributeAccessIssue]
        assert len(app_b.captured) == 0  # pyright: ignore[reportAttributeAccessIssue]
