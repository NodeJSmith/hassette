from hassette import App, AppConfig
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
        # --8<-- [start:split_handlers]
        await self.bus.on_state_change(
            self.app_config.motion_sensor,
            handler=self.on_motion_detected,
            changed_to="on",
            name="motion_on",
        )
        await self.bus.on_state_change(
            self.app_config.motion_sensor,
            handler=self.on_motion_cleared,
            changed_to="off",
            name="motion_off",
        )
        # --8<-- [end:split_handlers]

    async def on_motion_detected(self):
        if self.off_job is not None:
            self.off_job.cancel()
            self.off_job = None
        await self.api.turn_on(self.app_config.light, domain="light")

    async def on_motion_cleared(self):
        self.off_job = await self.scheduler.run_in(
            self.turn_off_light,
            delay=self.app_config.off_delay_seconds,
            name=OFF_JOB_NAME,
        )

    async def turn_off_light(self) -> None:
        self.off_job = None
        await self.api.turn_off(self.app_config.light, domain="light")
