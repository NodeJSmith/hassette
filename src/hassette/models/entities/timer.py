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
        """Starts a timer or restarts it with a provided duration.

        Args:
            duration: Custom duration to restart the timer with.
        """
        return self.api.call_service(
            domain=self.domain,
            service="start",
            target={"entity_id": self.entity_id},
            duration=duration,
        )

    def pause(self) -> Coroutine[Any, Any, None]:
        """Pauses a running timer, retaining the remaining duration for later continuation."""
        return self.api.call_service(
            domain=self.domain,
            service="pause",
            target={"entity_id": self.entity_id},
        )

    def cancel(self) -> Coroutine[Any, Any, None]:
        """Resets a timer's duration to the last known initial value without firing the timer finished event."""
        return self.api.call_service(
            domain=self.domain,
            service="cancel",
            target={"entity_id": self.entity_id},
        )

    def finish(self) -> Coroutine[Any, Any, None]:
        """Finishes a running timer earlier than scheduled."""
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
        """Changes a timer by adding or subtracting a given duration.

        Args:
            duration: Duration to add to or subtract from the running timer.
        """
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
        """Starts a timer or restarts it with a provided duration.

        Args:
            duration: Custom duration to restart the timer with.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="start",
            target={"entity_id": self.entity.entity_id},
            duration=duration,
        )

    def pause(self) -> None:
        """Pauses a running timer, retaining the remaining duration for later continuation."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="pause",
            target={"entity_id": self.entity.entity_id},
        )

    def cancel(self) -> None:
        """Resets a timer's duration to the last known initial value without firing the timer finished event."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="cancel",
            target={"entity_id": self.entity.entity_id},
        )

    def finish(self) -> None:
        """Finishes a running timer earlier than scheduled."""
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
        """Changes a timer by adding or subtracting a given duration.

        Args:
            duration: Duration to add to or subtract from the running timer.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="change",
            target={"entity_id": self.entity.entity_id},
            duration=duration,
        )
