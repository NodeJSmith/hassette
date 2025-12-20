from hassette import App, predicates as P


class DoorApp(App):
    async def on_initialize(self):
        # Logical AND (Implicit in list)
        # Triggers if:
        # 1. State changed from anything EXCEPT "unknown"
        # 2. AND battery level attribute is > 20
        self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_door_open,
            where=[
                P.Not(P.StateFrom("unknown")),
                P.AttrTo("battery_level", lambda x: x and x > 20),
            ],
        )

    async def on_door_open(self, event):
        pass
