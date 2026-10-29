from hassette import App, AppConfig, C, D, states


THRESHOLD = 25.0
DEBOUNCE_SECONDS = 10.0


class DebounceSensorApp(App[AppConfig]):
    """Log when a burst of rising temperature readings settles at or above a threshold."""

    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "sensor.outdoor_temperature",
            changed=C.Increased(),
            handler=self.on_temperature_stable,
            debounce=DEBOUNCE_SECONDS,
            name="outdoor_temp_debounced",
        )

    async def on_temperature_stable(
        self,
        new_state: D.StateNew[states.SensorState],
        old_state: D.StateOld[states.SensorState],
    ) -> None:
        try:
            new_temp = float(str(new_state.value))
        except (TypeError, ValueError):
            return

        if new_temp >= THRESHOLD:
            self.logger.info(
                "Temperature rose to %.1f°C (at or above %.1f°C threshold) from %s (no further rise for %ss)",
                new_temp,
                THRESHOLD,
                old_state.value,
                DEBOUNCE_SECONDS,
            )
