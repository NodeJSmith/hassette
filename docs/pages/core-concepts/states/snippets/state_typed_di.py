from hassette import App, AppConfig, D, states


class MotionApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_door_change,
            name="front_door",
        )

    async def on_door_change(
        self,
        new: D.StateNew[states.BinarySensorState],
        old: D.MaybeStateOld[states.BinarySensorState],
    ) -> None:
        # old is None when the app starts and there is no previous event
        previous = old.value if old else "unknown"
        self.logger.info("Door: %s -> %s", previous, new.value)
