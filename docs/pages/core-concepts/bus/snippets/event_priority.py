from hassette import App, AppConfig


# Topic-derived default — no event_priority= passed

# --8<-- [start:derived_default]
class DerivedApp(App[AppConfig]):
    async def on_initialize(self):
        # sensor.* state changes classify as "low" — shed under saturation.
        await self.bus.on_state_change(
            "sensor.power_meter",
            handler=self.on_reading,
            name="power_meter",
        )
        # light.* state changes classify as "normal" — never shed by tier.
        await self.bus.on_state_change(
            "light.kitchen",
            handler=self.on_light,
            name="kitchen_light",
        )

    async def on_reading(self):
        self.logger.info("Power reading received")

    async def on_light(self):
        self.logger.info("Kitchen light changed")
# --8<-- [end:derived_default]


# Opting a sensor listener out of shedding

# --8<-- [start:opt_out_of_shedding]
class EnergyBillingApp(App[AppConfig]):
    async def on_initialize(self):
        # Every reading feeds a running total, so a shed event is a wrong total.
        # "normal" restores the lossless block-and-wait behavior.
        await self.bus.on_state_change(
            "sensor.energy_meter",
            handler=self.on_reading,
            name="energy_meter",
            event_priority="normal",
        )

    async def on_reading(self):
        self.logger.info("Energy reading recorded")
# --8<-- [end:opt_out_of_shedding]


# CRITICAL — never shed, even with drop_newest

# --8<-- [start:critical_never_sheds]
class SmokeAlarmApp(App[AppConfig]):
    async def on_initialize(self):
        # "critical" wins over backpressure="drop_newest": this listener
        # waits for a dispatch slot rather than skipping the event.
        await self.bus.on_state_change(
            "binary_sensor.smoke_detector",
            changed_to="on",
            handler=self.on_smoke,
            name="smoke_alert",
            event_priority="critical",
            backpressure="drop_newest",
        )

    async def on_smoke(self):
        await self.api.call_service(
            "notify", "persistent_notification",
            message="Smoke detected!",
        )
# --8<-- [end:critical_never_sheds]
