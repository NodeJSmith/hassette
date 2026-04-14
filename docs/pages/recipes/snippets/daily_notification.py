from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig


class DailyNotificationConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="DAILY_NOTIFICATION_")

    notify_time: tuple[int, int] = (8, 0)
    """Hour and minute for the daily notification (24-hour clock). Default: 08:00."""

    notify_service: str = "mobile_app_phone"
    """Home Assistant notify service name (the part after `notify.`). Default: mobile_app_phone."""

    message: str = "Good morning! Have a great day."
    """Message body sent with the notification."""


class DailyNotificationApp(App[DailyNotificationConfig]):
    async def on_initialize(self) -> None:
        self.scheduler.run_daily(
            self.send_notification,
            start=self.app_config.notify_time,
        )
        self.logger.info(
            "Daily notification scheduled at %02d:%02d via notify.%s",
            self.app_config.notify_time[0],
            self.app_config.notify_time[1],
            self.app_config.notify_service,
        )

    async def send_notification(self) -> None:
        await self.api.call_service(
            "notify",
            self.app_config.notify_service,
            message=self.app_config.message,
            title="Daily Reminder",
        )
        self.logger.info("Daily notification sent.")
