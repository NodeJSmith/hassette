from hassette import App, AppConfig
from hassette.events import RawStateChangeEvent


class FanApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:literal_coercion]
        # The state is the string "on"; the bool literal is coerced to match it
        await self.bus.on_state_change("switch.fan", changed_to=True, handler=self.on_fan_on, name="fan_on")

        # String literals still compare exactly
        await self.bus.on_state_change("switch.fan", changed_to="on", handler=self.on_fan_on, name="fan_on_str")
        # --8<-- [end:literal_coercion]

    async def on_fan_on(self, event: RawStateChangeEvent) -> None: ...
