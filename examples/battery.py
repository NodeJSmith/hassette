from typing import Any

from hassette.core.apps import App, AppConfig, AppSync


# we subclass AppConfig to provide configuration specific to our app
# this data can be provided in hassette.toml, in an .env file, environment
# variables, or hardcoded - it uses pydantic settings under the hood
class BatteryConfig(AppConfig):
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

    async def initialize(self):
        await super().initialize()
        self.scheduler.run_cron(self.check_batteries, hour=6, day_of_month="*")
        assert self.app_config.threshold == 20

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
            values[device] = battery

        message = "Battery Level Report\n\n"
        if low:
            message += f"The following devices are low: (< {self.app_config.threshold}) "
            for device in low:
                message = message + device + " "
            message += "\n\n"

        message += "Battery Levels:\n\n"
        for device in sorted(values):
            message += f"{device}: {values[device]}\n"

        if low or self.app_config.always_send or self.app_config.force:
            # TODO: create a notify method on api
            await self.api.call_service(
                "notify",
                "notify",
                target={"entity_id": "my_phone"},
                message=message,
                title="Home Assistant Battery Report",
                name="andrew_mail",
            )


class BatterySync(AppSync[BatteryConfig]):
    """If you would prefer to have a fully synchronous app (e.g. have initialize and shutdown be sync)
    you can inherit from AppSync. All other functionality remains the same.
    """

    def initialize(self) -> None:
        super().initialize()
        self.scheduler.run_cron(self.check_batteries, hour=6, day_of_month="*")

    def check_batteries(self):
        """Everything that you can do asynchronously, you can also do synchronously.

        Just use the `.sync` property to access the synchronous version of the API.

        """
        states = self.api.sync.get_states()
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
            values[device] = battery

        message = "Battery Level Report\n\n"
        if low:
            message += f"The following devices are low: (< {self.app_config.threshold}) "
            for device in low:
                message = message + device + " "
            message += "\n\n"

        message += "Battery Levels:\n\n"
        for device in sorted(values):
            message += f"{device}: {values[device]}\n"

        if low or self.app_config.always_send or self.app_config.force:
            self.api.sync.call_service(
                "notify",
                "notify",
                target={"entity_id": "my_phone"},
                message=message,
                title="Home Assistant Battery Report",
                name="andrew_mail",
            )
