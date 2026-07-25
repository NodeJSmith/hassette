from hassette import App


class MyApp(App):
    async def my_callback(self):
        await self.api.notify(
            "Garage door left open",
            "mobile_app_phone",
            title="Alert",
        )
