"""Scheduler Overlap Demo.

Exercises the four scheduler overlap modes via run_every. Intended for the demo
stack — the restart job accumulates cancelled executions, populating the
cancelled count in the monitoring UI.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, ExecutionMode


class SchedulerOverlapDemoConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="scheduler_overlap_")
    enabled: bool = True
    work_seconds: float = 8.0
    interval_seconds: float = 3.0


class SchedulerOverlapDemo(App[SchedulerOverlapDemoConfig]):
    """Exercise the four scheduler overlap modes via run_every.

    One run_every job per ExecutionMode, with work_seconds > interval_seconds so each fire is
    due while the prior run is still going — the scheduler's dispatch-time overlap check then
    applies the mode (single suppresses, restart cancels, queued serializes, parallel overlaps).

    The restart job accumulates cancelled executions: each fire cancels the in-flight run, so the
    job detail panel and handlers-tab strip show a growing cancelled count alongside completions.
    """

    async def on_initialize(self) -> None:
        if not self.app_config.enabled:
            self.logger.info("SchedulerOverlapDemo disabled via config")
            return

        self.logger.info("Initializing SchedulerOverlapDemo")
        self.started: dict[str, int] = {}
        self.completed: dict[str, int] = {}
        cfg = self.app_config

        for mode in ExecutionMode:
            self.started[mode.value] = 0
            self.completed[mode.value] = 0
            await self.scheduler.run_every(
                self.make_job(mode),
                seconds=cfg.interval_seconds,
                mode=mode,
                name=f"scheduler_overlap_{mode.value}",
            )

    def make_job(self, mode: ExecutionMode) -> Callable[[], Coroutine[Any, Any, None]]:
        key = mode.value

        async def job() -> None:
            self.started[key] += 1
            run_id = self.started[key]
            self.logger.info("[sched:%s] START #%d", key, run_id)
            try:
                await asyncio.sleep(self.app_config.work_seconds)
            except asyncio.CancelledError:
                self.logger.info("[sched:%s] CANCELLED #%d", key, run_id)
                raise
            self.completed[key] += 1
            self.logger.info("[sched:%s] END #%d (completed=%d)", key, run_id, self.completed[key])

        return job
