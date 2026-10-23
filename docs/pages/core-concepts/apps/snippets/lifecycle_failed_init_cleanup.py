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
        except Exception:
            # on_shutdown does not run after a failed init
            await self.session.close()
            raise

    async def on_shutdown(self) -> None:
        await self.session.close()

    async def refresh(self) -> None:
        async with self.session.get("https://example.com/forecast") as resp:
            resp.raise_for_status()
