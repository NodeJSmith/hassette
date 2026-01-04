from hassette import App, AppConfig, states
from hassette import dependencies as D


class HelloWorldConfig(AppConfig):
    greeting: str = "Hello, World!"
    motion_sensor: str = "binary_sensor.motion"


class HelloWorld(App[HelloWorldConfig]):
    async def on_initialize(self) -> None:
        self.logger.info(self.app_config.greeting)

        # Listen for motion
        self.bus.on_state_change(self.app_config.motion_sensor, handler=self.on_motion, changed_to="on")

    async def on_motion(self, new_state: D.StateNew[states.BinarySensorState], entity_id: D.EntityId) -> None:
        """
        Instead of manually accessing event.payload.data, we use StateNew and EntityId
        type hints to automatically extract the new state and entity ID.
        """
        friendly_name = new_state.attributes.friendly_name or entity_id
        self.logger.info("Motion detected on %s!", friendly_name)
