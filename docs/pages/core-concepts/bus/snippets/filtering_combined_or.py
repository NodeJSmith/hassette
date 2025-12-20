from hassette import App, predicates as P


class LightApp(App):
    async def on_initialize(self):
        # Logical OR (AnyOf)
        # Triggers if ANY of the conditions match
        self.bus.on_call_service(
            domain="light",
            service="turn_on",
            where=P.AnyOf(
                P.ServiceDataWhere.from_kwargs(brightness=lambda b: b and b > 200),
                P.ServiceDataWhere.from_kwargs(color_name="red"),
            ),
            handler=self.on_bright_or_red_light,
        )

    async def on_bright_or_red_light(self, event):
        pass
