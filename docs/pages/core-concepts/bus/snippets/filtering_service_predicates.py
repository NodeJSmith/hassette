from hassette import App, C, P


class NotifyApp(App):
    async def on_initialize(self):
        self.bus.on_call_service(
            domain="notify",
            where=P.ServiceDataWhere.from_kwargs(
                message=lambda msg: "urgent" in str(msg).lower(),
                title=P.Not(C.StartsWith("DEBUG")),
            ),
            handler=self.on_urgent_notification,
        )

    async def on_urgent_notification(self, event):
        pass
