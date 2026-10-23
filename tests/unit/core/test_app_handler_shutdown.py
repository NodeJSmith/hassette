"""Process-exit app shutdown through AppHandler's own shutdown.

Uses the shared `app_handler` fixture (real AppHandler and AppLifecycleService on a mock Hassette
with default lifecycle settings), and drives `AppHandler.shutdown()` through the real coordinator.
"""

import asyncio

from hassette.core.app_handler import AppHandler

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

        async def slow_shutdown(name: str = app_key) -> None:
            await asyncio.sleep(APP_HOOK_SECONDS)
            finished.append(name)

        inst.shutdown.side_effect = slow_shutdown
        app_handler.registry.register_app(app_key, 0, inst)

    await app_handler.shutdown()

    assert sorted(finished) == ["first_app", "second_app"]
