from hassette import App


class NotifyApp(App):
    async def on_initialize(self):
        await self.api.notify("The garage door is still open", "mobile_app_phone")

        # A title and platform-specific push options
        await self.api.notify(
            "Motion in the driveway",
            "notify.mobile_app_phone",
            title="Security",
            data={"push": {"sound": "alarm.caf"}},
        )
