from pydantic import BaseModel, ConfigDict

from hassette import App, AppConfig, D


class DoorbellPressed(BaseModel):
    # Reject keys the model doesn't declare instead of ignoring them.
    model_config = ConfigDict(extra="forbid")

    camera: str
    snapshot: bool = False


class DoorbellApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on(
            topic="hass.event.doorbell_pressed",
            handler=self.on_doorbell,
            name="doorbell",
        )

    async def on_doorbell(
        self, doorbell: D.EventData[DoorbellPressed]
    ) -> None:
        self.logger.info("Doorbell at %s", doorbell.camera)
