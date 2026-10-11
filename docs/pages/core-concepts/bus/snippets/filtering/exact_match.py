from hassette import App, AppConfig, C
from hassette.events import RawStateChangeEvent


class CounterApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:exact_match]
        # No coercion: the string "1" does not match, a non-string value equal to 1 does
        await self.bus.on_attribute_change(
            "sensor.counter", "level", changed_to=C.Exact(1), handler=self.on_level, name="level_exact"
        )
        # --8<-- [end:exact_match]

    async def on_level(self, event: RawStateChangeEvent) -> None: ...
