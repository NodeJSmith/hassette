"""Motion-Activated Lights.

Turns a light on when motion is detected and off after motion clears.
Designed for multi-instance use — the same class drives different
motion sensor / light combinations via hassette.toml config.

Demo entities:
    - binary_sensor.movement_backyard
    - light.kitchen_lights
    - light.ceiling_lights
"""

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, entities


class MotionLightsConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="motion_lights_")

    motion_entity: str = "binary_sensor.movement_backyard"
    light_entity: str = "light.kitchen_lights"
    boost_brightness: int = 255
    default_brightness: int = 100
    off_delay: float = 60.0


class MotionLights(App[MotionLightsConfig]):
    """Turn a light on when motion is detected, off when it clears."""

    async def on_initialize(self) -> None:
        cfg = self.app_config
        self.logger.info(
            "Watching %s to control %s (brightness: %d)",
            cfg.motion_entity,
            cfg.light_entity,
            cfg.boost_brightness,
        )

        # Motion detected → turn light on immediately
        await self.bus.on_state_change(
            cfg.motion_entity,
            changed_to="on",
            handler=self.on_motion_detected,
            name="motion_lights.on_motion_detected",
        )

        # Motion cleared → turn light off after a delay
        await self.bus.on_state_change(
            cfg.motion_entity,
            changed_to="off",
            handler=self.on_motion_cleared,
            debounce=cfg.off_delay,
            name="motion_lights.on_motion_cleared",
        )

        # Log the current state of the motion sensor
        motion_state = self.states.binary_sensor.get(cfg.motion_entity)
        if motion_state:
            self.logger.info("Current motion state: %s", motion_state.value)

    async def on_motion_detected(self) -> None:
        """Motion detected — turn the light on at boost brightness."""
        cfg = self.app_config
        self.logger.info("Motion detected on %s", cfg.motion_entity)

        light = await self.api.get_entity(cfg.light_entity, entities.LightEntity)
        await light.turn_on(brightness=cfg.boost_brightness)
        self.logger.info("Turned on %s at brightness %d", cfg.light_entity, cfg.boost_brightness)

        # Refresh and log the updated state
        updated = await light.refresh()
        self.logger.debug("Light state after turn_on: %s (brightness=%s)", updated.value, updated.attributes.brightness)

    async def on_motion_cleared(self) -> None:
        """Motion cleared — turn off the light."""
        cfg = self.app_config
        self.logger.info("Motion cleared on %s", cfg.motion_entity)

        light = await self.api.get_entity(cfg.light_entity, entities.LightEntity)
        if light.state.value is True:
            self.logger.info("Turning off %s", cfg.light_entity)
            await light.turn_off()
        else:
            self.logger.debug("%s is already off", cfg.light_entity)
