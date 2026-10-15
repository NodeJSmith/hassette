"""Demo Stimulator.

Generates activity data for screenshots and visual QA. Triggers state
changes on demo entities to fire other apps' event handlers, and includes
a configurable failing job for error-state screenshots.

NOT a real automation — this exists solely to populate the UI with
representative data. Disable via hassette.toml when not needed.

Demo entities used:
    - sensor.outside_temperature
    - binary_sensor.movement_backyard
    - device_tracker.demo_paulus
    - input_boolean.test_toggle
"""

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig

BURST_DELAY_SECONDS = 3


class DemoStimulatorConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="demo_stim_")

    enable_failure: bool = True
    activity_interval: float = 20.0
    failure_interval: float = 5.0


class DemoStimulator(App[DemoStimulatorConfig]):
    """Generate UI activity data for screenshots."""

    async def on_initialize(self) -> None:
        cfg = self.app_config
        self.cycle = 0

        await self.bus.on_state_change(
            "input_boolean.test_toggle",
            handler=self.on_toggle_changed,
            name="demo_stimulator.on_toggle_changed",
        )

        await self.scheduler.run_in(self.trigger_activity_burst, BURST_DELAY_SECONDS, name="initial_burst")

        await self.scheduler.run_every(
            self.trigger_activity_cycle,
            seconds=cfg.activity_interval,
            name="activity_cycle",
            group="demo",
        )

        if cfg.enable_failure:
            await self.scheduler.run_every(
                self.failing_job,
                seconds=cfg.failure_interval,
                name="sensor_health_check",
                group="monitoring",
            )

        self.logger.info("Demo stimulator ready (failure=%s)", cfg.enable_failure)

    async def on_toggle_changed(self) -> None:
        self.logger.info("Test toggle changed")

    async def trigger_activity_burst(self) -> None:
        """Fire a burst of state changes to populate handler activity."""
        self.logger.info("Triggering initial activity burst")

        await self.api.set_state(
            "sensor.outside_temperature",
            "28.5",
            attributes={"unit_of_measurement": "°C", "friendly_name": "Outside Temperature"},
        )
        await self.api.set_state(
            "binary_sensor.movement_backyard",
            "on",
            attributes={"friendly_name": "Movement Backyard", "device_class": "motion"},
        )
        await self.api.call_service(
            "input_boolean",
            "toggle",
            target={"entity_id": "input_boolean.test_toggle"},
        )

        await self.scheduler.run_in(self.trigger_cooldown, BURST_DELAY_SECONDS, name="cooldown")

    async def trigger_cooldown(self) -> None:
        """Reset states after the burst."""
        await self.api.set_state(
            "sensor.outside_temperature",
            "22.0",
            attributes={"unit_of_measurement": "°C", "friendly_name": "Outside Temperature"},
        )
        await self.api.set_state(
            "binary_sensor.movement_backyard",
            "off",
            attributes={"friendly_name": "Movement Backyard", "device_class": "motion"},
        )
        self.logger.info("Activity burst complete — states reset")

    async def trigger_activity_cycle(self) -> None:
        """Periodic state changes to keep handler stats populated."""
        self.cycle += 1
        temp = 26.0 + (self.cycle % 5)
        self.logger.info("Activity cycle %d — setting temp to %.1f°", self.cycle, temp)

        await self.api.set_state(
            "sensor.outside_temperature",
            str(temp),
            attributes={"unit_of_measurement": "°C", "friendly_name": "Outside Temperature"},
        )

    async def failing_job(self) -> None:
        """Intentionally fails to demonstrate error UI states."""
        self.logger.error("About to fail — this is intentional for demo screenshots")
        await self.check_sensor_health()

    async def check_sensor_health(self) -> None:
        """Simulate a realistic failure path through nested calls."""
        readings = await self.collect_readings()
        self.validate_readings(readings)

    async def collect_readings(self) -> dict[str, float]:
        """Collect sensor readings — simulates an API timeout."""
        state = self.states.sensor.get("sensor.outside_temperature")
        if state and state.value is not None:
            return self.parse_sensor_response({"temperature": state.value, "humidity": None})
        msg = "Timed out waiting for sensor.outside_temperature after 10s"
        raise TimeoutError(msg)

    def validate_readings(self, readings: dict[str, float]) -> None:
        """Validate that all sensor readings are within expected ranges."""
        for key, value in readings.items():
            if value < -50 or value > 100:
                raise ValueError(f"Sensor '{key}' reading {value} is out of range [-50, 100]")

    def parse_sensor_response(self, response: dict[str, object]) -> dict[str, float]:
        """Parse raw sensor response into validated readings."""
        readings: dict[str, float] = {}
        for key, value in response.items():
            readings[key] = round(float(value), 2)  # pyright: ignore[reportArgumentType]
        return readings
