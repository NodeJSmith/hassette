from hassette import App, AppConfig, C, RawStateChangeEvent


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

    async def on_temperature_stable(self, event: RawStateChangeEvent) -> None:
        data = event.payload.data
        new_state = data.new_state
        old_state = data.old_state

        if new_state is None:
            return

        raw_new = new_state.get("state")
        raw_old = old_state.get("state") if old_state else None

        try:
            new_temp = float(str(raw_new))
        except (TypeError, ValueError):
            return

        if new_temp >= THRESHOLD:
            self.logger.info(
                "Temperature crossed %.1f°C threshold: %s → %.1f°C (stable for %ss)",
                THRESHOLD,
                raw_old,
                new_temp,
                DEBOUNCE_SECONDS,
            )
