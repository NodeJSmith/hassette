"""Bus Overlap Demo.

Exercises the four bus-handler execution modes with a self-driving event burst.
Intended for the demo stack — the restart handler accumulates cancelled
invocations, populating the cancelled count in the monitoring UI.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, ExecutionMode


class BusOverlapDemoConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="bus_overlap_")
    enabled: bool = True
    work_seconds: float = 2.0
    burst_size: int = 12
    burst_interval_seconds: float = 0.1
    drive_every_seconds: float = 5.0


class BusOverlapDemo(App[BusOverlapDemoConfig]):
    """Exercise the four bus-handler overlap modes with a self-driving event burst.

    One slow handler is registered per ExecutionMode on its own topic; a periodic driver
    emits a tight burst on every topic. burst_interval_seconds << work_seconds so each burst
    overlaps the in-flight handler, forcing each mode's behavior:

    - single: first runs, the rest are suppressed (guard.suppressed)
    - restart: each fire cancels the in-flight run, only the last completes
    - queued: serialized FIFO; bursts past the cap (10) are dropped (guard.dropped)
    - parallel: all run concurrently

    The restart handler accumulates cancelled executions, surfacing as a cancelled count in the
    global /handlers table and the listener detail panel.
    """

    async def on_initialize(self) -> None:
        if not self.app_config.enabled:
            self.logger.info("BusOverlapDemo disabled via config")
            return

        self.logger.info("Initializing BusOverlapDemo")
        self.started: dict[str, int] = {}
        self.completed: dict[str, int] = {}
        self.topics: dict[ExecutionMode, str] = {}

        for mode in ExecutionMode:
            topic = f"demo/bus/{mode.value}"
            self.topics[mode] = topic
            self.started[mode.value] = 0
            self.completed[mode.value] = 0
            await self.bus.on(
                topic=topic,
                handler=self.make_handler(mode),
                mode=mode,
                name=f"bus_overlap_{mode.value}",
            )

        await self.scheduler.run_every(
            self.drive_burst,
            seconds=self.app_config.drive_every_seconds,
            mode=ExecutionMode.PARALLEL,
            name="bus_overlap_driver",
        )

    def make_handler(self, mode: ExecutionMode) -> Callable[[], Coroutine[Any, Any, None]]:
        key = mode.value

        async def handler() -> None:
            self.started[key] += 1
            run_id = self.started[key]
            self.logger.info("[bus:%s] START #%d", key, run_id)
            try:
                await asyncio.sleep(self.app_config.work_seconds)
            except asyncio.CancelledError:
                self.logger.info("[bus:%s] CANCELLED #%d", key, run_id)
                raise
            self.completed[key] += 1
            self.logger.info("[bus:%s] END #%d (completed=%d)", key, run_id, self.completed[key])

        return handler

    async def drive_burst(self) -> None:
        cfg = self.app_config
        self.logger.info("[bus] driving burst of %d across all modes", cfg.burst_size)
        for _ in range(cfg.burst_size):
            for topic in self.topics.values():
                await self.bus.emit(topic, {})
            await asyncio.sleep(cfg.burst_interval_seconds)
