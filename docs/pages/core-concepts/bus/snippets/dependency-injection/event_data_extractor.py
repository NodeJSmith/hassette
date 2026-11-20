# --8<-- [start:sender]
from dataclasses import dataclass

from hassette import App, AppConfig, D, states

ALERT_TOPIC = "sensor.alert"


@dataclass(frozen=True, slots=True)
class SensorAlert:
    sensor_id: str
    reading: float


class FreezerWatchApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "sensor.freezer_temperature",
            handler=self.on_temperature_change,
            name="freezer_temperature",
        )

    async def on_temperature_change(
        self,
        new: D.StateNew[states.NumericSensorState],
    ) -> None:
        if new.value is None or new.value <= -10:
            return
        alert = SensorAlert(sensor_id=new.entity_id, reading=float(new.value))
        await self.bus.emit(ALERT_TOPIC, alert)
# --8<-- [end:sender]


# --8<-- [start:receiver]
class AlertApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on(
            topic=ALERT_TOPIC,
            handler=self.on_alert,
            name="alert_handler",
        )

    async def on_alert(self, alert: D.EventData[SensorAlert]) -> None:
        self.logger.warning(
            "Sensor %s reading: %.1f", alert.sensor_id, alert.reading
        )
# --8<-- [end:receiver]
