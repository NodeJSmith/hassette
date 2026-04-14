"""Complete example: app under test plus its pytest test suite."""

# --8<-- [start:app]
from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, D, states


class MotionLightsConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="motion_lights_")

    motion_sensor: str
    light: str


class MotionLights(App[MotionLightsConfig]):
    async def on_initialize(self) -> None:
        self.bus.on_state_change(
            self.app_config.motion_sensor,
            changed_to="on",
            handler=self.handle_motion,
        )

    async def handle_motion(self, new_state: D.StateNew[states.BinarySensorState]) -> None:
        await self.api.turn_on(self.app_config.light, domain="light")
# --8<-- [end:app]


# --8<-- [start:test]
from hassette.test_utils import AppTestHarness


async def test_motion_turns_on_light():
    async with AppTestHarness(
        MotionLights,
        config={
            "motion_sensor": "binary_sensor.hallway",
            "light": "light.hallway",
        },
    ) as harness:
        await harness.simulate_state_change(
            "binary_sensor.hallway",
            old_value="off",
            new_value="on",
        )

        harness.api_recorder.assert_called("turn_on", entity_id="light.hallway")


async def test_no_call_when_motion_clears():
    async with AppTestHarness(
        MotionLights,
        config={
            "motion_sensor": "binary_sensor.hallway",
            "light": "light.hallway",
        },
    ) as harness:
        await harness.simulate_state_change(
            "binary_sensor.hallway",
            old_value="on",
            new_value="off",
        )

        harness.api_recorder.assert_not_called("turn_on")
# --8<-- [end:test]
