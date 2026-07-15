from collections.abc import Coroutine
from typing import Any

from hassette.models.states import WaterHeaterState
from hassette.models.states.water_heater import WaterHeaterAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class WaterHeaterEntity(BaseEntity[WaterHeaterState, str]):
    @property
    def attributes(self) -> WaterHeaterAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "WaterHeaterEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(WaterHeaterEntitySyncFacade)

    def set_away_mode(
        self,
        *,
        away_mode: bool,
    ) -> Coroutine[Any, Any, None]:
        """Sets the away mode of a water heater.

        Args:
            away_mode: New value of away mode.
        """
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
        """Sets the target temperature of a water heater.

        Args:
            temperature: New target temperature for the water heater.
            operation_mode: New value of the operation mode. For a list of possible modes, refer to the integration
                documentation.
        """
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
        """Sets the operation mode of a water heater.

        Args:
            operation_mode: New value of the operation mode. For a list of possible modes, refer to the integration
                documentation.
        """
        return self.api.call_service(
            domain=self.domain,
            service="set_operation_mode",
            target={"entity_id": self.entity_id},
            operation_mode=operation_mode,
        )

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Turns on a water heater."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Turns off a water heater."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )


class WaterHeaterEntitySyncFacade(BaseEntitySyncFacade[WaterHeaterState, str]):
    """Synchronous facade for WaterHeaterEntity service methods."""

    def set_away_mode(
        self,
        *,
        away_mode: bool,
    ) -> None:
        """Sets the away mode of a water heater.

        Args:
            away_mode: New value of away mode.
        """
        self.entity.api.sync.call_service(
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
    ) -> None:
        """Sets the target temperature of a water heater.

        Args:
            temperature: New target temperature for the water heater.
            operation_mode: New value of the operation mode. For a list of possible modes, refer to the integration
                documentation.
        """
        self.entity.api.sync.call_service(
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
    ) -> None:
        """Sets the operation mode of a water heater.

        Args:
            operation_mode: New value of the operation mode. For a list of possible modes, refer to the integration
                documentation.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_operation_mode",
            target={"entity_id": self.entity.entity_id},
            operation_mode=operation_mode,
        )

    def turn_on(self) -> None:
        """Turns on a water heater."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Turns off a water heater."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )
