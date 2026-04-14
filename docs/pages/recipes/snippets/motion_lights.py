from hassette import App, AppConfig, D, states
from hassette.scheduler import ScheduledJob

MOTION_SENSOR = "binary_sensor.hallway_motion"
LIGHT = "light.hallway"
OFF_DELAY = 300  # seconds (5 minutes)
OFF_JOB_NAME = "motion_lights_off"


class MotionLightsConfig(AppConfig):
    motion_sensor: str = MOTION_SENSOR
    light: str = LIGHT
    off_delay: float = OFF_DELAY


class MotionLights(App[MotionLightsConfig]):
    _off_job: ScheduledJob | None = None

    async def on_initialize(self) -> None:
        self.bus.on_state_change(
            self.app_config.motion_sensor,
            handler=self.on_motion,
        )

    async def on_motion(self, new_state: D.StateNew[states.BinarySensorState]) -> None:
        if new_state.value == "on":
            # Motion detected — cancel any pending off job and turn the light on.
            if self._off_job is not None:
                self._off_job.cancel()
                self._off_job = None
            await self.api.turn_on(self.app_config.light, domain="light")

        elif new_state.value == "off":
            # Motion cleared — schedule the light to turn off after the delay.
            self._off_job = self.scheduler.run_in(
                self.turn_off_light,
                delay=self.app_config.off_delay,
                name=OFF_JOB_NAME,
            )

    async def turn_off_light(self) -> None:
        self._off_job = None
        await self.api.turn_off(self.app_config.light, domain="light")
