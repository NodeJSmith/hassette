"""Climate Controller.

Monitors outdoor temperature and HVAC current temperature to manage an
AC switch. Uses glob patterns to watch all temperature sensors and
attribute-change listeners on the HVAC entity.

Demo entities:
    - sensor.outside_temperature
    - climate.hvac
    - switch.ac
"""

from typing import Annotated

from pydantic_settings import SettingsConfigDict

from hassette import A, App, AppConfig, C, D, states


class ClimateControllerConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="climate_")

    temp_threshold: float = 24.0
    ac_switch: str = "switch.ac"
    climate_entity: str = "climate.hvac"
    check_interval: float = 300.0  # seconds


class ClimateController(App[ClimateControllerConfig]):
    """React to temperature changes and control an AC switch."""

    async def on_initialize(self) -> None:
        cfg = self.app_config
        self.logger.info(
            "Climate controller started — threshold=%.1f°, ac=%s",
            cfg.temp_threshold,
            cfg.ac_switch,
        )

        # Watch all temperature sensors via glob pattern
        self.bus.on_state_change(
            "sensor.*temperature*",
            changed=C.Increased(),
            handler=self.on_temp_increased,
        )

        self.bus.on_state_change(
            "sensor.*temperature*",
            changed=C.Decreased(),
            changed_from=C.Present(),
            handler=self.on_temp_decreased,
        )

        # Watch HVAC current_temperature attribute
        self.bus.on_attribute_change(
            cfg.climate_entity,
            "current_temperature",
            handler=self.on_hvac_temp_change,
        )

        # Periodic climate summary — group for easy filtering in the dashboard
        self.scheduler.run_every(
            self.log_climate_summary,
            seconds=cfg.check_interval,
            name="climate_summary",
            group="monitoring",
        )

    async def on_temp_increased(
        self,
        new_state: D.StateNew[states.SensorState],
        old_state: D.StateOld[states.SensorState],
        entity_id: D.EntityId,
    ) -> None:
        """An outdoor temperature sensor increased.

        Uses D.StateOld (not D.MaybeStateOld) — if there is no previous state
        (e.g. entity first appears), the handler is skipped entirely. This is
        useful when your handler logic requires the old state to be meaningful.
        A skipped invocation logs an error (without traceback) and is recorded
        in the telemetry DB as a DI failure. For a cleaner approach see
        on_temp_decreased which uses changed_from instead.
        """
        self.logger.info("%s temperature increased: %s -> %s", entity_id, old_state.value, new_state.value)

        try:
            temp = float(new_state.value) if new_state.value is not None else None
        except (ValueError, TypeError):
            temp = None

        if temp is not None and temp > self.app_config.temp_threshold:
            self.logger.info("Temperature %.1f° exceeds threshold, turning on AC", temp)
            await self.api.turn_on(self.app_config.ac_switch)

    async def on_temp_decreased(
        self,
        new_state: D.StateNew[states.SensorState],
        old_state: D.StateOld[states.SensorState],
        entity_id: D.EntityId,
    ) -> None:
        """An outdoor temperature sensor decreased.

        Uses changed_from=C.Present() on the bus subscription to prevent
        this handler from firing when there is no previous state. This is
        cleaner than relying on D.StateOld alone — the event is filtered
        before the handler is called, so no error is logged.
        """
        self.logger.info("%s temperature decreased: %s -> %s", entity_id, old_state.value, new_state.value)

        try:
            temp = float(new_state.value) if new_state.value is not None else None
        except (ValueError, TypeError):
            temp = None

        if temp is not None and temp <= self.app_config.temp_threshold:
            self.logger.info("Temperature %.1f° below threshold, turning off AC", temp)
            await self.api.turn_off(self.app_config.ac_switch)

    async def on_hvac_temp_change(
        self,
        current_temp: Annotated[float | None, A.get_attr_new("current_temperature")],
    ) -> None:
        """HVAC current_temperature attribute changed."""
        self.logger.info("HVAC current temperature is now: %s", current_temp)

        if current_temp is not None and current_temp > self.app_config.temp_threshold:
            self.logger.info("HVAC reports %.1f° — ensuring AC is on", current_temp)
            await self.api.turn_on(self.app_config.ac_switch)

    async def log_climate_summary(self) -> None:
        """Periodic summary of climate-related entities."""
        outside = self.states.sensor.get("sensor.outside_temperature")
        hvac = self.states.climate.get(self.app_config.climate_entity)
        ac = self.states.switch.get(self.app_config.ac_switch)

        self.logger.info(
            "Climate summary — outside=%s, hvac=%s (current=%s), ac=%s",
            outside.value if outside else "unknown",
            hvac.value if hvac else "unknown",
            hvac.attributes.current_temperature if hvac else "unknown",
            ac.value if ac else "unknown",
        )
