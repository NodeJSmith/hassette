from hassette import App


class ServiceWatchdogApp(App):
    async def on_initialize(self):
        # --8<-- [start:service]
        await self.bus.on_hassette_service_failed(
            handler=self.on_service_failed,
            name="service_watchdog",
        )
        # --8<-- [end:service]

    async def on_service_failed(self):
        self.logger.warning("A Hassette service failed and is being restarted")
