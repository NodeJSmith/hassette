from hassette import App, AppConfig
from pydantic_settings import SettingsConfigDict


class DailyConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="daily_")
    notify_service: str = "mobile_app_phone"
    notify_time: str = "07:30"


class DailyNotificationApp(App[DailyConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:cron_parse]
        h, m = self.app_config.notify_time.split(":")
        self.scheduler.run_cron(self.send_notification, f"{m} {h} * * 1-5")
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
