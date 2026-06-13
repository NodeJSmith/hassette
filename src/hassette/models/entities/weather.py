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
        return self._get_or_create_sync(WeatherEntitySyncFacade)

    def get_forecast(
        self,
        *,
        type: Type,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
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
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="get_forecasts",
            target={"entity_id": self.entity_id},
            type=type,
        )


class WeatherEntitySyncFacade(BaseEntitySyncFacade[WeatherState, str]):
    def get_forecast(
        self,
        *,
        type: Type,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
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
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="get_forecasts",
            target={"entity_id": self.entity.entity_id},
            type=type,
        )
