from hassette import App, C, P


class EnergyApp(App):
    async def on_initialize(self):
        # Fire when power consumption rises
        await self.bus.on_state_change(
            "sensor.plug_power",
            handler=self.on_power_increased,
            changed=C.Increased(),
            name="plug_power_up",
        )

        # Fire when battery level drops
        await self.bus.on_state_change(
            "sensor.phone_battery",
            handler=self.on_battery_decreased,
            changed=C.Decreased(),
            name="battery_down",
        )

        # Also works with attributes via P.AttrComparison
        await self.bus.on_state_change(
            "climate.bedroom",
            handler=self.on_brightness_increased,
            where=P.AttrComparison("current_temperature", C.Increased()),
            name="bedroom_temp_up",
        )

    async def on_power_increased(self, event):
        pass

    async def on_battery_decreased(self, event):
        pass

    async def on_brightness_increased(self, event):
        pass
