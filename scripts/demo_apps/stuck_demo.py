"""Stuck App Demo.

Demo app, not a real automation, used to reproduce the needs-restart flag for documentation
screenshots. `on_initialize()` starts a background task that swallows its cancellation, then fails.
Hassette shuts the failed instance down, the task outlives the teardown, and the instance is flagged
as needing a restart. `autostart = false` in hassette.toml: the task never ends until the process
does, so the app is started via the API only when a needs-restart screenshot is needed.
"""

import asyncio
import contextlib

from hassette import App, AppConfig


class StuckDemo(App[AppConfig]):
    """Fails to start and leaves a task running that ignores cancellation."""

    async def on_initialize(self) -> None:
        self.task_bucket.spawn(self.ignore_cancellation(), name="stuck_demo.poll")
        raise RuntimeError("stuck_demo: deliberate failure for needs-restart screenshots")

    async def ignore_cancellation(self) -> None:
        # The anti-pattern the needs-restart flag exists to surface: never let a cancellation through.
        while True:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(1)
