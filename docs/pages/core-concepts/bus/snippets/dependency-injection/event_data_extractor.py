from dataclasses import dataclass

from hassette import App, AppConfig, D


@dataclass(frozen=True, slots=True)
class SensorAlert:
    sensor_id: str
    reading: float


class AlertApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on(topic="sensor.alert", handler=self.on_alert, name="alert_handler")

    async def on_alert(self, alert: D.EventData[SensorAlert]) -> None:
        self.logger.warning("Sensor %s reading: %.1f", alert.sensor_id, alert.reading)
