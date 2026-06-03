from hassette import App, AppConfig


class OrchestratorApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:app_state_changed]
        # Fire whenever any app's status changes.
        await self.bus.on_app_state_changed(
            handler=self.on_any_app_change,
            name="any_app_status",
        )

        # Fire only when the sensor app reaches RUNNING.
        await self.bus.on_app_running(
            app_key="sensor_monitor",
            handler=self.on_sensor_ready,
            name="sensor_monitor_running",
        )

        # Fire when the sensor app begins stopping.
        await self.bus.on_app_stopping(
            app_key="sensor_monitor",
            handler=self.on_sensor_stopping,
            name="sensor_monitor_stopping",
        )
        # --8<-- [end:app_state_changed]

        # --8<-- [start:websocket]
        await self.bus.on_websocket_connected(
            handler=self.on_connected,
            name="ha_ws_connected",
        )
        await self.bus.on_websocket_disconnected(
            handler=self.on_disconnected,
            name="ha_ws_disconnected",
        )
        # --8<-- [end:websocket]

    async def on_any_app_change(self) -> None:
        self.logger.info("An app changed status")

    async def on_sensor_ready(self) -> None:
        self.logger.info("Sensor monitor is running")

    async def on_sensor_stopping(self) -> None:
        self.logger.warning("Sensor monitor is stopping")

    async def on_connected(self) -> None:
        self.logger.info("Connected to Home Assistant")

    async def on_disconnected(self) -> None:
        self.logger.warning("Lost connection to Home Assistant")
