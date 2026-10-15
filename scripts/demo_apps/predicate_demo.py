"""Predicate Demo.

Demonstrates scheduler ``where=`` predicates for docs screenshots.
Runs a short-interval job gated on motion detection — accumulates
a mix of success and skipped executions depending on the motion sensor
state toggled by the demo stimulator.

Demo entities used:
    - binary_sensor.movement_backyard (toggled by demo_stimulator)
"""

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig


class PredicateDemoConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="predicate_demo_")

    motion_entity: str = "binary_sensor.movement_backyard"
    check_interval: float = 8.0


class PredicateDemo(App[PredicateDemoConfig]):
    """Scheduled job with a where= predicate for screenshot capture."""

    async def on_initialize(self) -> None:
        cfg = self.app_config

        await self.scheduler.run_every(
            self.check_motion_zone,
            seconds=cfg.check_interval,
            name="motion_zone_check",
            where=self.is_motion_detected,
        )

    def is_motion_detected(self) -> bool:
        state = self.states.binary_sensor.get(self.app_config.motion_entity)
        return state is not None and state.value is True

    async def check_motion_zone(self) -> None:
        self.logger.info("Motion zone active — running check")
