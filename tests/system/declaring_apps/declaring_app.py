"""App fixture that declares a button, a switch and a sensor for the hass-hassette system tests.

Kept out of ``tests/system/apps/`` so the other system tests, which load every app there, don't
declare entities they never look at.
"""

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, D, IntegrationButton, IntegrationSensor, IntegrationSwitch


class DeclaringAppConfig(AppConfig):
    """Configuration for DeclaringApp."""

    model_config = SettingsConfigDict(env_prefix="declaring_app_")

    # Turned off to check that a declaration the instance drops is removed from Home Assistant.
    declare_switch: bool = True


class DeclaringApp(App[DeclaringAppConfig]):
    """Counts button presses in a sensor and mirrors its switch's commanded state."""

    presses: IntegrationSensor
    ping: IntegrationButton
    # Declared only while declare_switch is on.
    occupied: IntegrationSwitch | None = None

    async def on_initialize(self) -> None:
        self.presses = await self.integration.add_sensor("presses", name="Presses", state_class="measurement")
        self.ping = await self.integration.add_button("ping", name="Ping", on_press=self.on_ping)
        if self.app_config.declare_switch:
            self.occupied = await self.integration.add_switch("occupied", name="Occupied", on_toggle=self.on_occupied)

    async def on_ping(self) -> None:
        # The value is typed as any sensor value: None before the first press, then the number this sets
        # (restored as a number after a restart).
        count = self.presses.value
        await self.presses.set((int(count) if isinstance(count, int | float) else 0) + 1)

    async def on_occupied(self, on: D.SwitchCommand) -> None:
        assert self.occupied is not None, "the switch's handler runs only while it is declared"
        await self.occupied.set(on)
