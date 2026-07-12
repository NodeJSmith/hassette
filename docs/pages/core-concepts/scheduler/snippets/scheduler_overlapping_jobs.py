import asyncio

from hassette import App, AppConfig


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        self.sync_lock = asyncio.Lock()
        await self.scheduler.run_every(
            self.sync_data, seconds=30, name="sync_data"
        )

    async def sync_data(self) -> None:
        if self.sync_lock.locked():
            return  # previous run still in progress — skip this tick
        async with self.sync_lock:
            ...  # do work
