import apprise  # pyright: ignore[reportMissingImports]
from hassette import App, AppConfig


class NotifyConfig(AppConfig):
    notify_url: str = "tgram://bot_token/chat_id"


class NotifyApp(App[NotifyConfig]):
    async def on_initialize(self) -> None:
        self.notifier = apprise.Apprise()
        self.notifier.add(self.app_config.notify_url)
        self.logger.info("Notification service ready")
