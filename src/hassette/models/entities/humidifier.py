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
        """Call the humidifier.set_mode service.

        Args:
            mode: Operation mode. For example, "normal", "eco", or "away". For a list of possible values, refer to the
                integration documentation.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
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
        """Call the humidifier.set_humidity service.

        Args:
            humidity: Target humidity.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_humidity",
            target={"entity_id": self.entity_id},
            humidity=humidity,
        )

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Call the humidifier.turn_on service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Call the humidifier.turn_off service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Call the humidifier.toggle service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
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
        """Call the humidifier.set_mode service synchronously.

        Args:
            mode: Operation mode. For example, "normal", "eco", or "away". For a list of possible values, refer to the
                integration documentation.

        Returns:
            None.
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
        """Call the humidifier.set_humidity service synchronously.

        Args:
            humidity: Target humidity.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_humidity",
            target={"entity_id": self.entity.entity_id},
            humidity=humidity,
        )

    def turn_on(self) -> None:
        """Call the humidifier.turn_on service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Call the humidifier.turn_off service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self) -> None:
        """Call the humidifier.toggle service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )
