from hassette import App, AppConfig


class MyConfig(AppConfig):
    phone_entity: str = "sensor.phone"


class MyApp(App[MyConfig]):
    async def on_initialize(self):
        # --8<-- [start:attribute_change]
        await self.bus.on_attribute_change(
            "sensor.phone",
            "battery_level",
            handler=self.on_battery,
            name="phone_battery",
        )
        # --8<-- [end:attribute_change]

    async def on_battery(self) -> None:
        pass
