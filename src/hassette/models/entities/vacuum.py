from collections.abc import Coroutine
from typing import Any

from hassette.models.states import VacuumState
from hassette.models.states.vacuum import VacuumAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class VacuumEntity(BaseEntity[VacuumState, str]):
    @property
    def attributes(self) -> VacuumAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "VacuumEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(VacuumEntitySyncFacade)

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Call the vacuum.turn_on service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Call the vacuum.turn_off service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Call the vacuum.toggle service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    def stop(self) -> Coroutine[Any, Any, None]:
        """Call the vacuum.stop service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="stop",
            target={"entity_id": self.entity_id},
        )

    def locate(self) -> Coroutine[Any, Any, None]:
        """Call the vacuum.locate service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="locate",
            target={"entity_id": self.entity_id},
        )

    def start_pause(self) -> Coroutine[Any, Any, None]:
        """Call the vacuum.start_pause service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="start_pause",
            target={"entity_id": self.entity_id},
        )

    def start(self) -> Coroutine[Any, Any, None]:
        """Call the vacuum.start service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="start",
            target={"entity_id": self.entity_id},
        )

    def pause(self) -> Coroutine[Any, Any, None]:
        """Call the vacuum.pause service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="pause",
            target={"entity_id": self.entity_id},
        )

    def return_to_base(self) -> Coroutine[Any, Any, None]:
        """Call the vacuum.return_to_base service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="return_to_base",
            target={"entity_id": self.entity_id},
        )

    def clean_spot(self) -> Coroutine[Any, Any, None]:
        """Call the vacuum.clean_spot service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="clean_spot",
            target={"entity_id": self.entity_id},
        )

    def clean_area(
        self,
        *,
        cleaning_area_id: str,
    ) -> Coroutine[Any, Any, None]:
        """Call the vacuum.clean_area service.

        Args:
            cleaning_area_id: Areas to clean.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="clean_area",
            target={"entity_id": self.entity_id},
            cleaning_area_id=cleaning_area_id,
        )

    def send_command(
        self,
        *,
        command: str,
        params: Any | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the vacuum.send_command service.

        Args:
            command: Command to execute. The commands are integration-specific.
            params: Parameters for the command. The parameters are integration-specific.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="send_command",
            target={"entity_id": self.entity_id},
            command=command,
            params=params,
        )

    def set_fan_speed(
        self,
        *,
        fan_speed: str,
    ) -> Coroutine[Any, Any, None]:
        """Call the vacuum.set_fan_speed service.

        Args:
            fan_speed: Fan speed. The value depends on the integration. Some integrations have speed steps, like
                'medium'. Some use a percentage, between 0 and 100.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_fan_speed",
            target={"entity_id": self.entity_id},
            fan_speed=fan_speed,
        )


class VacuumEntitySyncFacade(BaseEntitySyncFacade[VacuumState, str]):
    """Synchronous facade for VacuumEntity service methods."""

    def turn_on(self) -> None:
        """Call the vacuum.turn_on service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Call the vacuum.turn_off service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self) -> None:
        """Call the vacuum.toggle service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )

    def stop(self) -> None:
        """Call the vacuum.stop service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="stop",
            target={"entity_id": self.entity.entity_id},
        )

    def locate(self) -> None:
        """Call the vacuum.locate service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="locate",
            target={"entity_id": self.entity.entity_id},
        )

    def start_pause(self) -> None:
        """Call the vacuum.start_pause service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="start_pause",
            target={"entity_id": self.entity.entity_id},
        )

    def start(self) -> None:
        """Call the vacuum.start service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="start",
            target={"entity_id": self.entity.entity_id},
        )

    def pause(self) -> None:
        """Call the vacuum.pause service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="pause",
            target={"entity_id": self.entity.entity_id},
        )

    def return_to_base(self) -> None:
        """Call the vacuum.return_to_base service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="return_to_base",
            target={"entity_id": self.entity.entity_id},
        )

    def clean_spot(self) -> None:
        """Call the vacuum.clean_spot service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="clean_spot",
            target={"entity_id": self.entity.entity_id},
        )

    def clean_area(
        self,
        *,
        cleaning_area_id: str,
    ) -> None:
        """Call the vacuum.clean_area service synchronously.

        Args:
            cleaning_area_id: Areas to clean.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="clean_area",
            target={"entity_id": self.entity.entity_id},
            cleaning_area_id=cleaning_area_id,
        )

    def send_command(
        self,
        *,
        command: str,
        params: Any | None = None,
    ) -> None:
        """Call the vacuum.send_command service synchronously.

        Args:
            command: Command to execute. The commands are integration-specific.
            params: Parameters for the command. The parameters are integration-specific.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="send_command",
            target={"entity_id": self.entity.entity_id},
            command=command,
            params=params,
        )

    def set_fan_speed(
        self,
        *,
        fan_speed: str,
    ) -> None:
        """Call the vacuum.set_fan_speed service synchronously.

        Args:
            fan_speed: Fan speed. The value depends on the integration. Some integrations have speed steps, like
                'medium'. Some use a percentage, between 0 and 100.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_fan_speed",
            target={"entity_id": self.entity.entity_id},
            fan_speed=fan_speed,
        )
