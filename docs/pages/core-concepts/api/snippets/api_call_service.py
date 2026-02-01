from hassette import App


class NotifyApp(App):
    async def on_initialize(self):
        await self.api.call_service(
            domain="notify",
            service="mobile_app_phone",
            message="Hello from Hassette!",
            data={"priority": "high"},
        )
