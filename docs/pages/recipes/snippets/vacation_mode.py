import random

from hassette import App, AppConfig
from hassette.scheduler import ScheduledJob

VACATION_TOGGLE = "input_boolean.vacation_mode"
LIGHTS = ("light.living_room", "light.kitchen", "light.bedroom")
CHECK_INTERVAL = 900  # seconds (15 minutes)
PRESENCE_JOB_NAME = "vacation_presence_sim"


class VacationModeConfig(AppConfig):
    vacation_toggle: str = VACATION_TOGGLE
    lights: tuple[str, ...] = LIGHTS
    check_interval: float = CHECK_INTERVAL


class VacationMode(App[VacationModeConfig]):
    _presence_job: ScheduledJob | None = None

    async def on_initialize(self) -> None:
        self.bus.on_state_change(
            self.app_config.vacation_toggle,
            changed_to="on",
            handler=self.on_vacation_start,
        )
        self.bus.on_state_change(
            self.app_config.vacation_toggle,
            changed_to="off",
            handler=self.on_vacation_end,
        )

    async def on_vacation_start(self) -> None:
        self.logger.info("Vacation mode enabled — starting presence simulation")
        self._presence_job = self.scheduler.run_every(
            self.simulate_presence,
            interval=self.app_config.check_interval,
            name=PRESENCE_JOB_NAME,
        )

    async def on_vacation_end(self) -> None:
        self.logger.info("Vacation mode disabled — stopping presence simulation")
        if self._presence_job is not None:
            self._presence_job.cancel()
            self._presence_job = None
        for light in self.app_config.lights:
            await self.api.turn_off(light, domain="light")

    async def simulate_presence(self) -> None:
        light = random.choice(self.app_config.lights)
        state = await self.api.get_state(f"{light}")
        if state.value == "on":
            await self.api.turn_off(light, domain="light")
            self.logger.debug("Presence sim: turned off %s", light)
        else:
            await self.api.turn_on(light, domain="light")
            self.logger.debug("Presence sim: turned on %s", light)
