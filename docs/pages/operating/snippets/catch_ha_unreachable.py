from hassette import App, AppConfig

# --8<-- [start:imports]
from hassette.exceptions import CommandNotSentError, OutcomeUnknownError

# --8<-- [end:imports]


class OutageTolerantApp(App[AppConfig]):
    async def refresh(self) -> None:
        # --8<-- [start:catch]
        try:
            light = await self.api.get_state("light.kitchen")  # REST
            await self.api.turn_on("light.porch")  # WebSocket
        except (CommandNotSentError, OutcomeUnknownError):
            self.logger.warning("HA unreachable, skipping refresh")
            return
        # --8<-- [end:catch]
        self.logger.info("Kitchen light is %s", light.value)
