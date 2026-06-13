from collections.abc import Coroutine
from typing import Any

from hassette.models.states import TimerState
from hassette.models.states.timer import TimerAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class TimerEntity(BaseEntity[TimerState, str]):
    @property
    def attributes(self) -> TimerAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "TimerEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(TimerEntitySyncFacade)

    def start(
        self,
        *,
        duration: dict[str, int] | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the timer.start service.

        Args:
            duration: Custom duration to restart the timer with.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="start",
            target={"entity_id": self.entity_id},
            duration=duration,
        )

    def pause(self) -> Coroutine[Any, Any, None]:
        """Call the timer.pause service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="pause",
            target={"entity_id": self.entity_id},
        )

    def cancel(self) -> Coroutine[Any, Any, None]:
        """Call the timer.cancel service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="cancel",
            target={"entity_id": self.entity_id},
        )

    def finish(self) -> Coroutine[Any, Any, None]:
        """Call the timer.finish service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="finish",
            target={"entity_id": self.entity_id},
        )

    def change(
        self,
        *,
        duration: dict[str, int],
    ) -> Coroutine[Any, Any, None]:
        """Call the timer.change service.

        Args:
            duration: Duration to add to or subtract from the running timer.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="change",
            target={"entity_id": self.entity_id},
            duration=duration,
        )


class TimerEntitySyncFacade(BaseEntitySyncFacade[TimerState, str]):
    """Synchronous facade for TimerEntity service methods."""

    def start(
        self,
        *,
        duration: dict[str, int] | None = None,
    ) -> None:
        """Call the timer.start service synchronously.

        Args:
            duration: Custom duration to restart the timer with.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="start",
            target={"entity_id": self.entity.entity_id},
            duration=duration,
        )

    def pause(self) -> None:
        """Call the timer.pause service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="pause",
            target={"entity_id": self.entity.entity_id},
        )

    def cancel(self) -> None:
        """Call the timer.cancel service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="cancel",
            target={"entity_id": self.entity.entity_id},
        )

    def finish(self) -> None:
        """Call the timer.finish service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="finish",
            target={"entity_id": self.entity.entity_id},
        )

    def change(
        self,
        *,
        duration: dict[str, int],
    ) -> None:
        """Call the timer.change service synchronously.

        Args:
            duration: Duration to add to or subtract from the running timer.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="change",
            target={"entity_id": self.entity.entity_id},
            duration=duration,
        )
