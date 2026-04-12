from hassette import App
from hassette.exceptions import HassetteError


class SunApp(App):
    async def on_initialize(self):
        try:
            state = await self.api.get_state("sun.sun")
            self.logger.info("Sun is %s", state.state)
        except HassetteError as e:
            self.logger.error("HA API error: %s", e)
