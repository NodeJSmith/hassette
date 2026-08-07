from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig

# Variations on the recipe's main app — the config below mirrors
# daily_notification.py so both files describe the same app.


class DailyNotificationConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="DAILY_NOTIFICATION_")

    notify_time: str = "08:00"
    notify_service: str = "mobile_app_phone"


class DailyNotificationApp(App[DailyNotificationConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:cron_parse]
        h, m = self.app_config.notify_time.split(":")
        await self.scheduler.run_cron(
            self.send_notification, f"{m} {h} * * 1-5", name="send_notification"
        )
        # --8<-- [end:cron_parse]

    # --8<-- [start:send_notification]
    async def send_notification(self) -> None:
        temp_state = await self.api.get_state("sensor.outdoor_temperature")
        message = f"Good morning! It's {temp_state.value}° outside."
        await self.api.call_service(
            "notify",
            self.app_config.notify_service,
            message=message,
            title="Daily Reminder",
        )

    # --8<-- [end:send_notification]
