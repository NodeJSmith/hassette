from datetime import datetime
from decimal import Decimal
from typing import Annotated

from hassette import A, App


class SensorApp(App):
    async def on_sensor_change(
        self,
        # String "23.5" → float 23.5
        temperature: Annotated[float, A.get_attr_new("temperature")],
        # String "99" → int 99
        battery: Annotated[int | None, A.get_attr_new("battery_level")],
        # String "0.1234" → Decimal("0.1234") (high precision)
        precise_value: Annotated[Decimal | None, A.get_attr_new("value")],
        # ISO string → datetime object
        last_seen: Annotated[datetime | None, A.get_attr_new("last_seen")],
    ):
        self.logger.info(
            "Temp: %.1f°C, Battery: %d%%, Precise: %s, Last seen: %s",
            temperature,
            battery or 0,
            precise_value,
            last_seen,
        )
