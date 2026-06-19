from hassette import App, AppConfig


# ---------------------------------------------------------------------------
# Composition: drop_newest + single
# ---------------------------------------------------------------------------

# --8<-- [start:drop_newest_single]
class ComposedApp(App[AppConfig]):
    async def on_initialize(self):
        await self.bus.on_state_change(
            "sensor.power_meter",
            handler=self.on_reading,
            name="power_meter",
            backpressure="drop_newest",
            mode="single",
        )

    async def on_reading(self):
        self.logger.info("Power reading received")
# --8<-- [end:drop_newest_single]


# ---------------------------------------------------------------------------
# DROP_NEWEST — skip if the whole bus is saturated
# ---------------------------------------------------------------------------

# --8<-- [start:drop_newest_basic]
class PowerApp(App[AppConfig]):
    async def on_initialize(self):
        await self.bus.on_state_change(
            "sensor.power_meter",
            handler=self.on_reading,
            name="power_meter",
            backpressure="drop_newest",
        )

    async def on_reading(self):
        # Under normal load, every reading dispatches.
        # When the global dispatch semaphore is saturated,
        # this event is dropped instead of queuing behind it.
        self.logger.info("Power reading received")
# --8<-- [end:drop_newest_basic]


# ---------------------------------------------------------------------------
# BLOCK (default) — must-run handler; always waits for a slot
# ---------------------------------------------------------------------------

# --8<-- [start:block_explicit]
class AlertApp(App[AppConfig]):
    async def on_initialize(self):
        # backpressure="block" is the default — shown here for clarity.
        # This handler always waits for a dispatch slot; it never drops.
        await self.bus.on_state_change(
            "binary_sensor.smoke_detector",
            changed_to="on",
            handler=self.on_smoke,
            name="smoke_alert",
            backpressure="block",
        )

    async def on_smoke(self):
        await self.api.call_service(
            "notify", "persistent_notification",
            message="Smoke detected!",
        )
# --8<-- [end:block_explicit]
