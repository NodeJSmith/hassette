"""Process-exit app shutdown through AppHandler's own shutdown.

Uses the shared `app_handler` fixture (real AppHandler and AppLifecycleService on a mock Hassette
with default lifecycle settings), and drives `AppHandler.shutdown()` through the real coordinator.
"""

import asyncio
import logging
from unittest.mock import Mock

import pytest

from hassette.core.app_handler import AppHandler
from hassette.resources.shutdown_outcome import ShutdownOutcome

from .conftest import make_mock_app_instance

# Each app's on_shutdown takes this long: well inside `shutdown_timeout_seconds`, but two of them run
# back to back would outlast a bound shared across apps that is smaller than their sum.
APP_HOOK_SECONDS = 1.5


async def test_later_apps_are_not_cut_off_at_process_exit(app_handler: AppHandler) -> None:
    """Every app's shutdown hooks run to completion at exit, however many apps there are."""
    finished: list[str] = []

    for app_key in ("first_app", "second_app"):
        inst = make_mock_app_instance(instance_name=app_key)
        inst.app_key = app_key

        async def slow_shutdown(name: str = app_key) -> ShutdownOutcome:
            await asyncio.sleep(APP_HOOK_SECONDS)
            finished.append(name)
            return ShutdownOutcome()

        inst.shutdown.side_effect = slow_shutdown
        app_handler.registry.register_app(app_key, 0, inst)

    await app_handler.shutdown()

    assert sorted(finished) == ["first_app", "second_app"]


async def test_force_terminal_reaches_registry_apps(app_handler: AppHandler, caplog: pytest.LogCaptureFixture) -> None:
    """Registry apps aren't children of the handler, so force-terminating it reaches them explicitly,
    and the ones whose stop hadn't finished are named in one ERROR.
    """
    instances = {}
    for app_key, finished in (("stuck_app", False), ("done_app", True)):
        inst = make_mock_app_instance(instance_name=app_key)
        inst.app_key = app_key
        inst.unique_name = f"MockApp.{app_key}"
        inst.shutdown_completed = finished
        inst._force_terminal = Mock()
        app_handler.registry.register_app(app_key, 0, inst)
        instances[app_key] = inst

    with caplog.at_level(logging.ERROR):
        app_handler._force_terminal()

    for inst in instances.values():
        inst._force_terminal.assert_called_once()
    (error,) = [r.getMessage() for r in caplog.records if r.message.startswith("Force-terminating apps")]
    assert "stuck_app" in error
    assert "done_app" not in error
