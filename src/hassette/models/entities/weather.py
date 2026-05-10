from typing import Literal

from hassette.models.states import WeatherState
from hassette.models.states.weather import WeatherAttributes

from .base import BaseEntity

Type = Literal["daily", "hourly", "twice_daily"]


class WeatherEntity(BaseEntity[WeatherState, str]):
    @property
    def attributes(self) -> WeatherAttributes:
        return self.state.attributes

    async def get_forecast(
        self,
        *,
        type: Type,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="get_forecast",
            target={"entity_id": self.entity_id},
            type=type,
        )

    async def get_forecasts(
        self,
        *,
        type: Literal["daily", "hourly", "twice_daily"],
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="get_forecasts",
            target={"entity_id": self.entity_id},
            type=type,
        )
