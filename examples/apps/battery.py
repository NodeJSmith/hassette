# compare to: https://github.com/AppDaemon/appdaemon/blob/dev/conf/example_apps/battery.py

from typing import Any

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, states


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
        values: dict[str, int] = {}
        low: list[states.BaseState] = []
        # iterate over self.states to get a DomainStates class per known domain
        for ds in self.states.values():
            # iterate over each entity in the domain to check battery levels
            for device in ds.values():
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
                message = message + device.entity_id + " "
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
