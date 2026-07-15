from collections.abc import Coroutine
from typing import Any

from hassette.models.states import HumidifierState
from hassette.models.states.humidifier import HumidifierAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class HumidifierEntity(BaseEntity[HumidifierState, str]):
    @property
    def attributes(self) -> HumidifierAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "HumidifierEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(HumidifierEntitySyncFacade)

    def set_mode(
        self,
        *,
        mode: str,
    ) -> Coroutine[Any, Any, None]:
        """Sets the mode of a humidifier.

        Args:
            mode: Operation mode. For example, "normal", "eco", or "away". For a list of possible values, refer to the
                integration documentation.
        """
        return self.api.call_service(
            domain=self.domain,
            service="set_mode",
            target={"entity_id": self.entity_id},
            mode=mode,
        )

    def set_humidity(
        self,
        *,
        humidity: int,
    ) -> Coroutine[Any, Any, None]:
        """Sets the target humidity of a humidifier.

        Args:
            humidity: Target humidity.
        """
        return self.api.call_service(
            domain=self.domain,
            service="set_humidity",
            target={"entity_id": self.entity_id},
            humidity=humidity,
        )

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Turns on a humidifier."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Turns off a humidifier."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Toggles a humidifier on/off."""
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )


class HumidifierEntitySyncFacade(BaseEntitySyncFacade[HumidifierState, str]):
    """Synchronous facade for HumidifierEntity service methods."""

    def set_mode(
        self,
        *,
        mode: str,
    ) -> None:
        """Sets the mode of a humidifier.

        Args:
            mode: Operation mode. For example, "normal", "eco", or "away". For a list of possible values, refer to the
                integration documentation.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_mode",
            target={"entity_id": self.entity.entity_id},
            mode=mode,
        )

    def set_humidity(
        self,
        *,
        humidity: int,
    ) -> None:
        """Sets the target humidity of a humidifier.

        Args:
            humidity: Target humidity.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_humidity",
            target={"entity_id": self.entity.entity_id},
            humidity=humidity,
        )

    def turn_on(self) -> None:
        """Turns on a humidifier."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Turns off a humidifier."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self) -> None:
        """Toggles a humidifier on/off."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )
