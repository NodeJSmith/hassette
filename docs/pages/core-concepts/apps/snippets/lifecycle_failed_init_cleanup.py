import aiohttp

from hassette import App


class WeatherApp(App):
    session: aiohttp.ClientSession

    async def on_initialize(self) -> None:
        self.session = aiohttp.ClientSession()
        try:
            await self.bus.on_state_change(
                "sun.sun", handler=self.refresh, name="sun_refresh"
            )
            await self.refresh()
        except BaseException:
            # on_shutdown doesn't run after a failed or timed-out init;
            # BaseException also catches the timeout's CancelledError
            await self.session.close()
            raise

    async def on_shutdown(self) -> None:
        await self.session.close()

    async def refresh(self) -> None:
        async with self.session.get("https://example.com/forecast") as resp:
            resp.raise_for_status()
