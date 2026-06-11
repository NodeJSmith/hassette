from hassette import App


class SystemApp(App):
    async def on_initialize(self):
        # --8<-- [start:get_config]
        config = await self.api.get_config()
        self.logger.info("HA version: %s", config.get("version"))
        self.logger.info("Location: %s", config.get("location_name"))
        # --8<-- [end:get_config]

        # --8<-- [start:get_services]
        services = await self.api.get_services()
        light_services = list(services.get("light", {}).keys())
        self.logger.info("Light services: %s", light_services)
        # --8<-- [end:get_services]

        # --8<-- [start:get_panels]
        panels = await self.api.get_panels()
        self.logger.info("Available panels: %s", list(panels.keys()))
        # --8<-- [end:get_panels]

        # --8<-- [start:delete_entity]
        await self.api.delete_entity("sensor.stale_custom_sensor")
        # --8<-- [end:delete_entity]
