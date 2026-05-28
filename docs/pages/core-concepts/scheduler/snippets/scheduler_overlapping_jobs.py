import asyncio

from hassette import App, AppConfig


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        self._sync_lock = asyncio.Lock()
        self.scheduler.run_every(self.sync_data, seconds=30)

    async def sync_data(self) -> None:
        if self._sync_lock.locked():
            return  # previous run still in progress — skip this tick
        async with self._sync_lock:
            ...  # do work
