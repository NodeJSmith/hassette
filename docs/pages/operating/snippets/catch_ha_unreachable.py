import aiohttp

from hassette import App, AppConfig
from hassette.exceptions import ConnectionClosedError


class OutageTolerantApp(App[AppConfig]):
    async def refresh(self) -> None:
        # --8<-- [start:catch]
        try:
            # REST: raises aiohttp.ClientError while HA is down
            light = await self.api.get_state("light.kitchen")
            # WebSocket: raises ConnectionClosedError
            await self.api.turn_on("light.porch")
        except (aiohttp.ClientError, ConnectionClosedError):
            self.logger.warning("HA unreachable, skipping refresh")
            return
        # --8<-- [end:catch]
        self.logger.info("Kitchen light is %s", light.value)
