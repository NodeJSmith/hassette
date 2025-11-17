# compare to: https://github.com/AppDaemon/appdaemon/blob/dev/conf/example_apps/battery.py

from typing import Annotated, Any

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, AppSync, states
from hassette import dependencies as D


# we subclass AppConfig to provide configuration specific to our app
# this data can be provided in hassette.toml, in an .env file, environment
# variables, or hardcoded - it uses pydantic settings under the hood
class BatteryConfig(AppConfig):
    # you can add a model config and set an env_prefix to simplify your environment variables
    # e.g. BATTERY_THRESHOLD=10

    # otherwise you can set this with HASSETTE__APPS__BATTERY__CONFIG__THRESHOLD=10
    # which is not the most user friendly
    model_config = SettingsConfigDict(env_prefix="battery_")

    threshold: float = 20
    always_send: bool = False
    force: bool = False


def try_cast_int(value: Any | None):
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class Battery(App[BatteryConfig]):
    """App is generic, so add your config class to the type parameter and you'll have
    fully typed access to the config values.

    The app config is provided to the `__init__` method at startup - if you have multiple
    versions of the same app defined in your hassette.toml, there will be an instance created
    for each one, each receiving their respective configuration.
    """

    async def on_initialize(self):
        self.scheduler.run_in(self.check_batteries, 1)
        assert self.app_config.threshold == 10  # from what is in hassette.toml

    async def check_batteries(self):
        # get_states and all other methods are fully typed, including their Attributes
        # list[AiTaskState | AssistSatelliteState | AutomationState ... BaseState[Unknown]]
        states = await self.api.get_states()

        # you can also get states as raw data - these are TypedDicts, so you can still get type hints
        # but only at the general "State" level, not to the BatteryState or LightState level
        _states_raw = await self.api.get_states_raw()

        values = {}
        low = []
        for device in states:
            if not (hasattr(device.attributes, "battery") or hasattr(device.attributes, "battery_level")):
                continue

            battery_value = getattr(device.attributes, "battery", None)
            battery_level_value = getattr(device.attributes, "battery_level", None)

            battery = try_cast_int(battery_value) or try_cast_int(battery_level_value)
            if battery is None:
                continue

            if battery < self.app_config.threshold:
                low.append(device)
            values[device.entity_id] = battery

        message = "Battery Level Report\n\n"
        if low:
            message += f"The following devices are low: (< {self.app_config.threshold}) "
            for device in low:
                message = message + device + " "
            message += "\n\n"

        message += "Battery Levels:\n\n"
        for device, value in sorted(values.items()):
            message += f"{device}: {value}\n"

        if low or self.app_config.always_send or self.app_config.force:
            await self.api.call_service(
                "notify",
                "my_mobile_phone",
                message=message,
                title="Home Assistant Battery Report",
                name="andrew_mail",
            )


class BatterySync(AppSync[BatteryConfig]):
    """If you would prefer to have a fully synchronous app (e.g. have on_initialize and on_shutdown be sync)
    you can inherit from AppSync.

    The standard `on_initialize` is replaced with `on_initialize_sync`, which is run in a thread, the same
    with `on_shutdown` being replaced with `on_shutdown_sync`.

    The API is fully available in synchronous form via the `.sync` property on the `api` property.

    The Bus and Scheduler can work with sync or async callbacks, so you can use them as normal.
    """

    def on_initialize_sync(self) -> None:
        """Use the `on_initialize` lifecycle hook to set up the app."""
        self.scheduler.run_in(self.check_batteries, 10)
        self.bus.on_state_change("*", handler=self.handle_sensor_event)

    def handle_sensor_event(
        self,
        new_state: Annotated[states.SensorState, D.StateNew],
        battery_level: Annotated[int | None, D.AttrNew("battery_level")],
        entity_id: Annotated[str, D.EntityId],
    ) -> None:
        """Example handler demonstrating dependency injection for battery monitoring.

        Instead of manually accessing event.payload.data.new_state, we use DI to extract:
        - new_state: The full sensor state object
        - battery_level: The battery_level attribute (if present)
        - entity_id: The entity ID from the event
        """
        if battery_level is not None and battery_level < self.app_config.threshold:
            friendly_name = new_state.attributes.friendly_name or entity_id
            self.logger.warning("%s battery is low: %d%%", friendly_name, battery_level)

    def check_batteries(self):
        """Everything that you can do asynchronously, you can also do synchronously.

        Just use the `.sync` property to access the synchronous version of the API.

        """
        self.logger.info("Checking batteries (sync version)")
        states = self.api.sync.get_states()
        self.logger.info("Found %d states", len(states))
        values = {}
        low = []
        for device in states:
            if not (hasattr(device.attributes, "battery") or hasattr(device.attributes, "battery_level")):
                continue

            battery_value = getattr(device.attributes, "battery", None)
            battery_level_value = getattr(device.attributes, "battery_level", None)

            battery = try_cast_int(battery_value) or try_cast_int(battery_level_value)
            if battery is None:
                continue

            if battery < self.app_config.threshold:
                low.append(device)
            values[device.entity_id] = battery

        message = "Battery Level Report\n\n"
        if low:
            message += f"The following devices are low: (< {self.app_config.threshold}) "
            for device in low:
                message = message + device + " "
            message += "\n\n"

        message += "Battery Levels:\n\n"
        for device, value in sorted(values.items()):
            message += f"{device}: {value}\n"

        if low or self.app_config.always_send or self.app_config.force:
            self.api.sync.call_service(
                "notify", "my_mobile_phone", message=message, title="Home Assistant Battery Report", name="andrew_mail"
            )
