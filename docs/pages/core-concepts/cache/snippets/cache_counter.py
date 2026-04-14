from hassette import App, AppConfig, P


class MotionCounterApp(App[AppConfig]):
    async def on_initialize(self):
        # Restore counter from cache, or start at 0
        self.motion_count = self.cache.get("motion_count", 0)
        self.logger.info("Motion count restored: %s", self.motion_count)

        self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_motion,
            where=P.StateTo("on"),
        )

    async def on_motion(self, event):
        self.motion_count += 1
        self.cache["motion_count"] = self.motion_count
        self.logger.info("Total motion events: %s", self.motion_count)
