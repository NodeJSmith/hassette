from hassette import App
from hassette import predicates as P


class PredicatesFilteringExample(App):
    async def on_initialize(self):
        # Combine multiple conditions
        self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_door_open,
            changed_to="on",
            where=[
                P.Not(P.StateFrom("unknown")),  # Ignore transitions from unknown
                P.AttrTo("battery_level", lambda x: x is not None and x > 20),  # Only if battery OK
            ],
        )

        # Use logical operators
        self.bus.on_state_change(
            "media_player.living_room",
            handler=self.on_media_change,
            where=P.StateTo(P.IsIn(["playing", "paused"])),  # state is in ["playing", "paused"]
        )

        # Custom predicates with Guard
        def is_workday(event):
            from datetime import datetime

            return datetime.now().weekday() < 5

        self.bus.on_state_change("binary_sensor.motion", handler=self.on_workday_motion, where=P.Guard(is_workday))

    async def on_door_open(self, event):
        pass

    async def on_media_change(self, event):
        pass

    async def on_workday_motion(self, event):
        pass
