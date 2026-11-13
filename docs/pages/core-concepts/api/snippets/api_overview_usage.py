from hassette import App
from hassette.exceptions import HassetteError


class SunApp(App):
    async def on_initialize(self):
        try:
            state = await self.api.get_state("sun.sun")
            self.logger.info("Sun is %s", state.value)
            await self.api.call_service(
                "light",
                "turn_on",
                target={"entity_id": "light.porch"},
            )
        except HassetteError as exc:
            self.logger.error("HA API error: %s", exc)
