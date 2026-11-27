from whenever import Instant

from hassette import (
    App,
    AppConfig,
    D,
    IntegrationButton,
    IntegrationSensor,
    IntegrationSwitch,
)


class CatFeederApp(App[AppConfig]):
    feed: IntegrationButton
    paused: IntegrationSwitch
    last_fed: IntegrationSensor

    # --8<-- [start:declare]
    async def on_initialize(self):
        self.feed = await self.integration.add_button(
            "feed_now",
            name="Feed now",
            on_press=self.on_feed,
        )
        self.paused = await self.integration.add_switch(
            "paused",
            name="Paused",
            on_toggle=self.on_paused,
        )
        self.last_fed = await self.integration.add_sensor(
            "last_fed",
            name="Last fed",
            device_class="timestamp",
        )
    # --8<-- [end:declare]

    # --8<-- [start:press]
    async def on_feed(self):
        await self.api.call_service(
            "switch", "turn_on", target={"entity_id": "switch.cat_feeder"}
        )
        await self.last_fed.set(Instant.now())
    # --8<-- [end:press]

    # --8<-- [start:toggle]
    async def on_paused(self, on: D.SwitchCommand):
        await self.paused.set(on)
        self.logger.info("Feeding paused: %s", on)
    # --8<-- [end:toggle]


class PortionConfig(AppConfig):
    portion_grams: int = 40


class PortionApp(App[PortionConfig]):
    async def on_initialize(self):
        # --8<-- [start:sensor]
        self.portion = await self.integration.add_sensor(
            "portion",
            name="Portion",
            unit="g",
            device_class="weight",
            state_class="measurement",
        )
        await self.portion.set(self.app_config.portion_grams)
        # --8<-- [end:sensor]

        # --8<-- [start:enum]
        self.mode = await self.integration.add_sensor(
            "mode",
            name="Mode",
            device_class="enum",
            options=["normal", "diet", "away"],
            default_entity_id="sensor.cat_feeder_mode",
        )
        await self.mode.set("normal", attributes={"since": "today"})
        # --8<-- [end:enum]

        # --8<-- [start:category]
        self.reset_feeder = await self.integration.add_button(
            "reset_feeder",
            name="Reset feeder",
            on_press=self.on_reset_feeder,
            entity_category="config",
        )
        # --8<-- [end:category]

        # --8<-- [start:icon]
        self.last_fed = await self.integration.add_sensor(
            "last_fed",
            name="Last fed",
            device_class="timestamp",
            icon="mdi:food-drumstick",
        )
        # --8<-- [end:icon]

    async def on_reset_feeder(self):
        await self.mode.set("normal")
