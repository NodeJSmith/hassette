from collections.abc import Coroutine
from typing import Any, Literal

from hassette.models.states import WeatherState
from hassette.models.states.weather import WeatherAttributes

from .base import BaseEntity, BaseEntitySyncFacade

Type = Literal["daily", "hourly", "twice_daily"]


class WeatherEntity(BaseEntity[WeatherState, str]):
    @property
    def attributes(self) -> WeatherAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "WeatherEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(WeatherEntitySyncFacade)

    def get_forecast(
        self,
        *,
        type: Type,
    ) -> Coroutine[Any, Any, None]:
        """Call the weather.get_forecast service.

        Args:
            type: The scope of the weather forecast.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="get_forecast",
            target={"entity_id": self.entity_id},
            type=type,
        )

    def get_forecasts(
        self,
        *,
        type: Literal["daily", "hourly", "twice_daily"],
    ) -> Coroutine[Any, Any, None]:
        """Call the weather.get_forecasts service.

        Args:
            type: The scope of the weather forecast.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="get_forecasts",
            target={"entity_id": self.entity_id},
            type=type,
        )


class WeatherEntitySyncFacade(BaseEntitySyncFacade[WeatherState, str]):
    """Synchronous facade for WeatherEntity service methods."""

    def get_forecast(
        self,
        *,
        type: Type,
    ) -> None:
        """Call the weather.get_forecast service synchronously.

        Args:
            type: The scope of the weather forecast.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="get_forecast",
            target={"entity_id": self.entity.entity_id},
            type=type,
        )

    def get_forecasts(
        self,
        *,
        type: Literal["daily", "hourly", "twice_daily"],
    ) -> None:
        """Call the weather.get_forecasts service synchronously.

        Args:
            type: The scope of the weather forecast.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="get_forecasts",
            target={"entity_id": self.entity.entity_id},
            type=type,
        )
