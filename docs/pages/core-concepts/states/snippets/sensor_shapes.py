from hassette import App, AppConfig, D, states
from hassette.exceptions import EntityNotInViewError


class SensorShapeApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:subscribe]
        await self.bus.on_state_change(
            "sensor.outdoor_temperature",
            handler=self.on_temperature_change,
            name="outdoor_temperature",
        )
        # --8<-- [end:subscribe]

    # --8<-- [start:annotation]
    async def on_temperature_change(
        self, new: D.StateNew[states.NumericSensorState]
    ):
        if new.value is not None:
            self.logger.info("Outdoor temp: %.1f", new.value)
    # --8<-- [end:annotation]

    async def read_via_accessor(self):
        # --8<-- [start:accessor]
        for entity_id, sensor in self.states.numeric_sensor.items():
            if sensor.value is not None:
                self.logger.info("%s: %.1f", entity_id, sensor.value)
        # --8<-- [end:accessor]

    async def escape_hatch(self):
        # --8<-- [start:escape-hatch]
        # self.states.sensor still contains every sensor, including
        # entities excluded from the numeric_sensor view.
        every_sensor = self.states.sensor.get("outdoor_temperature")
        numeric_only = self.states.numeric_sensor.get("outdoor_temperature")
        # --8<-- [end:escape-hatch]
        return every_sensor, numeric_only

    async def lookup_semantics(self):
        # --8<-- [start:lookup]
        # .get() returns None for a non-member
        maybe_enum = self.states.enum_sensor.get("outdoor_temperature")

        # [] raises EntityNotInViewError for a non-member
        try:
            self.states.enum_sensor["outdoor_temperature"]
        except EntityNotInViewError as exc:
            self.logger.warning("Not an enum sensor: %s", exc)
        # --8<-- [end:lookup]
        return maybe_enum
