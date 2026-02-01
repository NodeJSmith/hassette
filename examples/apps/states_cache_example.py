"""Example app demonstrating the States resource for local state caching.

This app shows how to use self.states to access entity states without API calls.
The state cache is automatically kept up-to-date via state change events.
"""

from pydantic import Field

from hassette import App, AppConfig
from hassette.models import states


class StatesCacheConfig(AppConfig):
    """Configuration for the states cache example app."""

    low_battery_threshold: int = Field(20, ge=0, le=100, description="Battery level threshold for warnings")
    check_interval: int = Field(300, ge=60, description="How often to check states (seconds)")


class StatesCacheExample(App[StatesCacheConfig]):
    """Example app demonstrating state cache usage patterns."""

    async def on_initialize(self):
        """Set up periodic state checks using the cache."""
        self.logger.info("Starting States Cache Example")

        # Log initial state summary
        await self.log_state_summary()

        # Schedule periodic checks using cached states
        self.scheduler.run_every(
            self.check_battery_levels, interval=self.app_config.check_interval, name="battery_check"
        )

        self.scheduler.run_every(self.log_state_summary, interval=600, name="state_summary")

    async def log_state_summary(self):
        """Log a summary of entities using the state cache."""
        # Access all states without API call
        available = unknown = unavailable = all_states = 0
        for ds in self.states.values():
            for state in ds.values():
                all_states += 1
                if state.is_unavailable:
                    unavailable += 1
                elif state.is_unknown:
                    unknown += 1
                else:
                    available += 1

        self.logger.info("=== State Cache Summary ===")
        self.logger.info("Total entities: %s", all_states)
        self.logger.info("Available: %s, Unavailable: %s, Unknown: %s", available, unavailable, unknown)

        # Count by domain using domain accessors
        self.logger.info("Lights: %s", len(self.states.light))
        self.logger.info("Sensors: %s", len(self.states.sensor))
        self.logger.info("Switches: %s", len(self.states.switch))
        self.logger.info("Binary Sensors: %s", len(self.states.binary_sensor))

        # Example: Find all lights that are on
        lights_on = sum(1 for _, light in self.states.light if light.value == "on")
        self.logger.info("Lights currently on: %s", lights_on)

    async def check_battery_levels(self):
        """Check battery levels across all sensors using the cache.

        This demonstrates efficient iteration over cached states without API calls.
        """
        low_batteries = []

        # Iterate over all sensors in the cache
        for entity_id, sensor in self.states.sensor:
            # Check if this sensor has a battery_level attribute
            if hasattr(sensor.attributes, "battery_level"):
                battery_level = sensor.attributes.battery_level  # pyright: ignore[reportAttributeAccessIssue]

                if battery_level is not None and battery_level < self.app_config.low_battery_threshold:
                    friendly_name = sensor.attributes.friendly_name or entity_id
                    low_batteries.append((friendly_name, battery_level))

        if low_batteries:
            self.logger.warning("=== Low Battery Devices ===")
            for name, level in sorted(low_batteries, key=lambda x: x[1]):
                self.logger.warning("%s: %s%%", name, level)

            # Could send notification here
            message = f"Low battery alert: {len(low_batteries)} devices below {self.app_config.low_battery_threshold}%"
            self.logger.info("Would send notification: %s", message)
        else:
            self.logger.debug("All batteries are above threshold")

    async def demonstrate_typed_access(self):
        """Show various ways to access states with typing."""
        # Domain-specific accessor
        bedroom_light = self.states.light.get("light.bedroom")
        if bedroom_light:
            self.logger.info("Bedroom light: %s", bedroom_light.value)
            if bedroom_light.attributes.brightness:
                self.logger.info("Brightness: %s", bedroom_light.attributes.brightness)

        # Typed generic accessor
        living_climate = self.states[states.ClimateState].get("climate.living_room")
        if living_climate:
            self.logger.info("Climate: %s°F", living_climate.attributes.current_temperature)

        # Check for existence with None-safe access
        optional_light = self.states.light.get("light.maybe_exists")
        if optional_light:
            self.logger.info("Optional light exists: %s", optional_light.value)
        else:
            self.logger.debug("Optional light does not exist")

        # Iterate over domain
        self.logger.info("All switches:")
        for entity_id, switch in self.states.switch:
            self.logger.info("  %s: %s", entity_id, switch.value)

    async def demonstrate_availability_checks(self):
        """Show how to check entity availability before taking action."""
        light_id = "light.living_room"

        # Get state from cache
        light = self.states.light.get(light_id)

        if not light:
            self.logger.error("%s not found in state cache", light_id)
            return

        if light.is_unavailable:
            self.logger.warning("%s is unavailable - cannot control", light_id)
            return

        # Safe to control the light
        if light.value == "off":
            await self.api.turn_on(light_id, brightness=128)
            self.logger.info("Turned on %s", light_id)

    async def demonstrate_aggregation(self):
        """Show how to aggregate data from multiple cached states."""
        # Calculate average temperature from multiple sensors
        temp_sensors = [
            "sensor.bedroom_temp",
            "sensor.living_room_temp",
            "sensor.kitchen_temp",
        ]

        temps = []
        for entity_id in temp_sensors:
            sensor = self.states.sensor.get(entity_id)
            if sensor and not sensor.is_unavailable:
                try:
                    temp = float(sensor.value)  # type: ignore
                    temps.append(temp)
                except (ValueError, TypeError):
                    self.logger.warning("Could not parse temperature from %s: %s", entity_id, sensor.value)

        if temps:
            avg_temp = sum(temps) / len(temps)
            min_temp = min(temps)
            max_temp = max(temps)

            self.logger.info("Temperature stats: avg=%.1f°F, min=%.1f°F, max=%.1f°F", avg_temp, min_temp, max_temp)

    async def demonstrate_filtering(self):
        """Show how to filter entities by criteria using the cache."""
        # Find all lights above 50% brightness
        bright_lights = []

        for entity_id, light in self.states.light:
            if light.value == "on" and light.attributes.brightness:
                if light.attributes.brightness > 127:  # > 50%
                    friendly_name = light.attributes.friendly_name or entity_id
                    bright_lights.append((friendly_name, light.attributes.brightness))

        if bright_lights:
            self.logger.info("=== Bright Lights (>50%) ===")
            for name, brightness in sorted(bright_lights, key=lambda x: x[1], reverse=True):
                percentage = int((brightness / 255) * 100)
                self.logger.info("%s: %s%%", name, percentage)

        # Find all open doors/windows
        open_contacts = []
        for entity_id, sensor in self.states.binary_sensor:
            if sensor.value == "on":  # Binary sensors: on = open/detected
                if "door" in entity_id or "window" in entity_id:
                    friendly_name = sensor.attributes.friendly_name or entity_id
                    open_contacts.append(friendly_name)

        if open_contacts:
            self.logger.warning("Open doors/windows: %s", ", ".join(open_contacts))
