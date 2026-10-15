"""Backpressure Demo.

Drives a slow ``drop_newest`` listener past the dispatch concurrency limit so the
bus sheds the newest events at the acquire gate. Populates the backpressure drop
count and rate in the monitoring UI's listener detail panel.
"""

import asyncio

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, BackpressurePolicy, ExecutionMode


class BackpressureDemoConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="backpressure_")
    enabled: bool = True
    work_seconds: float = 3.0
    burst_size: int = 80
    burst_interval_seconds: float = 0.02
    drive_every_seconds: float = 12.0


class BackpressureDemo(App[BackpressureDemoConfig]):
    """Saturate the dispatch semaphore so a ``drop_newest`` listener sheds load.

    One slow handler runs in parallel mode on a single topic. A periodic driver emits a
    burst larger than ``lifecycle.max_concurrent_dispatches`` (default 50); once the
    semaphore is locked, the ``drop_newest`` policy skips the remaining events at the
    acquire gate instead of waiting for a slot. Each skip increments the listener's
    backpressure-dropped counter, which surfaces as the "Backpressure Dropped" stat
    (count and rate) in the listener detail panel.
    """

    async def on_initialize(self) -> None:
        if not self.app_config.enabled:
            self.logger.info("BackpressureDemo disabled via config")
            return

        self.logger.info("Initializing BackpressureDemo")
        self.started = 0
        self.completed = 0
        self.topic = "demo/backpressure/drop_newest"

        await self.bus.on(
            topic=self.topic,
            handler=self.slow_handler,
            mode=ExecutionMode.PARALLEL,
            backpressure=BackpressurePolicy.DROP_NEWEST,
            name="backpressure_drop_newest",
        )

        await self.scheduler.run_every(
            self.drive_burst,
            seconds=self.app_config.drive_every_seconds,
            mode=ExecutionMode.PARALLEL,
            name="backpressure_driver",
        )

    async def slow_handler(self) -> None:
        self.started += 1
        run_id = self.started
        self.logger.info("[backpressure] START #%d", run_id)
        await asyncio.sleep(self.app_config.work_seconds)
        self.completed += 1
        self.logger.info("[backpressure] END #%d (completed=%d)", run_id, self.completed)

    async def drive_burst(self) -> None:
        cfg = self.app_config
        self.logger.info("[backpressure] driving burst of %d", cfg.burst_size)
        for _ in range(cfg.burst_size):
            await self.bus.emit(self.topic, {})
            await asyncio.sleep(cfg.burst_interval_seconds)
