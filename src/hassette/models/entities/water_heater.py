from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import WaterHeaterState
from hassette.models.states.water_heater import WaterHeaterAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class WaterHeaterEntity(BaseEntity[WaterHeaterState, str]):
    @property
    def attributes(self) -> WaterHeaterAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "WaterHeaterEntitySyncFacade":
        if self._sync is None:
            self._sync = WaterHeaterEntitySyncFacade(entity=self)
        return cast("WaterHeaterEntitySyncFacade", self._sync)

    def set_away_mode(
        self,
        *,
        away_mode: bool,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_away_mode",
            target={"entity_id": self.entity_id},
            away_mode=away_mode,
        )

    def set_temperature(
        self,
        *,
        temperature: float,
        operation_mode: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_temperature",
            target={"entity_id": self.entity_id},
            temperature=temperature,
            operation_mode=operation_mode,
        )

    def set_operation_mode(
        self,
        *,
        operation_mode: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_operation_mode",
            target={"entity_id": self.entity_id},
            operation_mode=operation_mode,
        )

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )


class WaterHeaterEntitySyncFacade(BaseEntitySyncFacade[WaterHeaterState, str]):
    def set_away_mode(
        self,
        *,
        away_mode: bool,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_away_mode",
            target={"entity_id": self.entity.entity_id},
            away_mode=away_mode,
        )

    def set_temperature(
        self,
        *,
        temperature: float,
        operation_mode: str | None = None,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_temperature",
            target={"entity_id": self.entity.entity_id},
            temperature=temperature,
            operation_mode=operation_mode,
        )

    def set_operation_mode(
        self,
        *,
        operation_mode: str,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_operation_mode",
            target={"entity_id": self.entity.entity_id},
            operation_mode=operation_mode,
        )

    def turn_on(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )
