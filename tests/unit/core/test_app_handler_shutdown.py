"""Process-exit app shutdown through AppHandler's own shutdown.

Uses the shared `app_handler` fixture (real AppHandler and AppLifecycleService on a mock Hassette
with default lifecycle settings), and drives `AppHandler.shutdown()` through the real coordinator.
"""

import asyncio
from unittest.mock import Mock

from hassette.core.app_handler import AppHandler
from hassette.resources.teardown import TeardownReport

from .conftest import make_mock_app_instance

# Each app's on_shutdown takes this long: well inside the documented per-app shutdown timeout,
# but two of them back to back outlast any shared pool smaller than their sum.
APP_HOOK_SECONDS = 1.5


async def test_later_apps_are_not_cut_off_at_process_exit(app_handler: AppHandler) -> None:
    """Every app's shutdown hooks run to completion at exit, however many apps there are."""
    finished: list[str] = []

    for app_key in ("first_app", "second_app"):
        inst = make_mock_app_instance(instance_name=app_key)
        inst.app_key = app_key

        async def slow_shutdown(name: str = app_key) -> TeardownReport:
            await asyncio.sleep(APP_HOOK_SECONDS)
            finished.append(name)
            return TeardownReport()

        inst.shutdown.side_effect = slow_shutdown
        app_handler.registry.register_app(app_key, 0, inst)

    await app_handler.shutdown()

    assert sorted(finished) == ["first_app", "second_app"]


async def test_force_terminal_reaches_registry_apps(app_handler: AppHandler) -> None:
    """Registry apps aren't children of the handler, so force-terminating it reaches them explicitly,
    and the ones whose stop hadn't finished are named and recorded as force-terminated work.
    """
    app_handler.hassette.record_force_terminated = Mock()
    instances = {}
    for app_key, finished in (("stuck_app", False), ("done_app", True)):
        inst = make_mock_app_instance(instance_name=app_key)
        inst.app_key = app_key
        inst.unique_name = f"MockApp.{app_key}"
        inst.shutdown_completed = finished
        inst._force_terminal = Mock()
        app_handler.registry.register_app(app_key, 0, inst)
        instances[app_key] = inst

    app_handler._force_terminal()

    for inst in instances.values():
        inst._force_terminal.assert_called_once()
    (recorded,) = app_handler.hassette.record_force_terminated.call_args.args
    assert list(recorded) == ["MockApp.stuck_app"]
