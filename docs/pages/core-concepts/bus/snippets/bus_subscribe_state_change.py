from hassette import App, AppConfig
from hassette.bus import Subscription


class MotionApp(App[AppConfig]):
    sub: Subscription

    async def on_initialize(self):
        # --8<-- [start:subscribe]
        # Subscribe to state changes
        sub = self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_motion,
            changed_to="on",
        )

        # Subscriptions are cleaned up automatically on shutdown.
        # Unsubscribe manually only if you need to stop earlier:
        # sub.cancel()
        # --8<-- [end:subscribe]

    async def on_motion(self):
        pass
