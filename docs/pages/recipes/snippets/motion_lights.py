from hassette import App, AppConfig, D, states
from hassette.scheduler import ScheduledJob

OFF_JOB_NAME = "motion_lights_off"


class MotionLightsConfig(AppConfig):
    motion_sensor: str = "binary_sensor.hallway_motion"
    light: str = "light.hallway"
    off_delay_seconds: float = 300


class MotionLights(App[MotionLightsConfig]):
    off_job: ScheduledJob | None

    async def on_initialize(self) -> None:
        self.off_job = None
        await self.bus.on_state_change(
            self.app_config.motion_sensor,
            handler=self.on_motion,
            name="motion_sensor",
        )

    async def on_motion(self, new_state: D.StateNew[states.BinarySensorState]):
        if new_state.value is True:
            # Motion detected — cancel any pending off job and turn the light on.
            if self.off_job is not None:
                self.off_job.cancel()
                self.off_job = None
            await self.api.turn_on(self.app_config.light, domain="light")

        elif new_state.value is False:
            # Motion cleared — schedule the light to turn off after the delay.
            self.off_job = await self.scheduler.run_in(
                self.turn_off_light,
                delay=self.app_config.off_delay_seconds,
                name=OFF_JOB_NAME,
            )

    async def turn_off_light(self) -> None:
        self.off_job = None
        await self.api.turn_off(self.app_config.light, domain="light")
