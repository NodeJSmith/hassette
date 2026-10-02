"""Blocking Call Demo.

Demo app used to populate the blocking-calls findings for documentation screenshots. Two jobs
call one shared helper that makes a synchronous, loop-blocking call, the way an app might use a
synchronous HTTP client. Blocking-IO detection groups both jobs' events under that one call site.
It runs as two instances, so the app-wide overview lists the call site under both.

A third job hands the same helper to a loop callback and to a separate task while it waits, so
the loop stalls with no app credited for them: the diagnostics page's loop stalls panel.

NOT a real automation, and an example of what NOT to do: the fix is to run the helper in a
worker thread (``await asyncio.to_thread(load_report)``). `autostart = false` in hassette.toml:
it blocks the loop on purpose, so it's started via the API only when a screenshot needs it.
"""

import asyncio
import time

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig


class BlockingDemoConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="blocking_demo_")

    block_seconds: float = 0.3
    """How long each call blocks the loop. Well over the default 100ms detection threshold."""


def load_report(block_seconds: float) -> str:
    """Stands in for a synchronous client call (e.g. ``requests.get``) made on the event loop."""
    time.sleep(block_seconds)
    return "report"


async def load_report_in_task(block_seconds: float) -> None:
    load_report(block_seconds)


class BlockingDemo(App[BlockingDemoConfig]):
    """Two jobs reach the same blocking helper, so detection reports one call site to fix; a third
    blocks from code no job runs directly, so those stalls go uncredited.
    """

    async def on_initialize(self) -> None:
        await self.scheduler.run_every(self.refresh_dashboard, seconds=5, name="refresh_dashboard")
        await self.scheduler.run_every(self.sync_calendar, seconds=7, name="sync_calendar")
        await self.scheduler.run_every(self.poll_feed, seconds=11, name="poll_feed")

    async def refresh_dashboard(self) -> None:
        load_report(self.app_config.block_seconds)

    async def sync_calendar(self) -> None:
        load_report(self.app_config.block_seconds)

    async def poll_feed(self) -> None:
        """Block the loop from code this job doesn't run itself, so detection can't credit the app.

        The callback blocks with no task running (a framework stall); the separate task blocks while
        this job is suspended (a displaced stall).
        """
        loop = asyncio.get_running_loop()
        loop.call_soon(load_report, self.app_config.block_seconds)
        await asyncio.sleep(0.5)
        task = asyncio.create_task(load_report_in_task(self.app_config.block_seconds))
        await asyncio.sleep(0.5)
        await task
