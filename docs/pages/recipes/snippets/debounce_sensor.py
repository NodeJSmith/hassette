from hassette import App, AppConfig, C, D, states


THRESHOLD = 25.0
DEBOUNCE_SECONDS = 10.0


class DebounceSensorApp(App[AppConfig]):
    """React to stable temperature changes and log when a threshold is crossed."""

    async def on_initialize(self) -> None:
        self.bus.on_state_change(
            "sensor.outdoor_temperature",
            changed=C.Increased(),
            handler=self.on_temperature_stable,
            debounce=DEBOUNCE_SECONDS,
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
                "Temperature crossed %.1f°C threshold: %s → %.1f°C (stable for %ss)",
                THRESHOLD,
                old_state.value,
                new_temp,
                DEBOUNCE_SECONDS,
            )
