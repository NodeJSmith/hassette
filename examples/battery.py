from hassette.core.apps import App, AppConfig
from hassette.core.types import Any


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
    async def initialize(self):
        self.scheduler.run_cron(self.check_batteries, hour=6, day_of_month="*")

    async def check_batteries(self):
        states = await self.api.get_states()
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
            await self.api.call_service(
                "notify",
                "notify",
                target={"entity_id": "my_phone"},
                message=message,
                title="Home Assistant Battery Report",
                name="andrew_mail",
            )

    def check_batteries_sync(self):
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
