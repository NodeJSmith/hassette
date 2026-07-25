from hassette import App

NOTIFIER = "mobile_app_phone"


class AlertApp(App):
    async def on_initialize(self):
        available = await self.api.get_notify_services()
        if NOTIFIER not in available:
            raise ValueError(f"Unknown notifier {NOTIFIER!r}. Available: {available}")

        await self.api.notify("Alerts are wired up", NOTIFIER)
