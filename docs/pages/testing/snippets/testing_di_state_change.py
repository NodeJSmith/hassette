from hassette import D, states
from hassette.app import App, AppConfig
from hassette.test_utils import AppTestHarness


class SecurityConfig(AppConfig):
    door_entity: str


class SecurityApp(App[SecurityConfig]):
    async def on_initialize(self):
        self.bus.on_state_change(
            self.app_config.door_entity,
            changed_to="on",
            handler=self.on_door_opened,
        )

    async def on_door_opened(self, new_state: D.StateNew[states.BinarySensorState]):
        device_class = new_state.attributes.device_class
        if device_class == "door":
            await self.api.call_service("notify", "send_message", message="Door opened")


async def test_typed_state_change_handler():
    async with AppTestHarness(
        SecurityApp, config={"door_entity": "binary_sensor.front_door"}
    ) as harness:
        await harness.set_state(
            "binary_sensor.front_door", "off", device_class="door"
        )
        await harness.simulate_state_change(
            "binary_sensor.front_door", old_value="off", new_value="on"
        )
        harness.api_recorder.assert_called(
            "call_service", domain="notify", service="send_message", message="Door opened"
        )
