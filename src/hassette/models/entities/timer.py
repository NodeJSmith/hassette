from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import TimerState
from hassette.models.states.timer import TimerAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class TimerEntity(BaseEntity[TimerState, str]):
    @property
    def attributes(self) -> TimerAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "TimerEntitySyncFacade":
        if self._sync is None:
            self._sync = TimerEntitySyncFacade(entity=self)
        return cast("TimerEntitySyncFacade", self._sync)

    def start(
        self,
        *,
        duration: dict[str, int] | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="start",
            target={"entity_id": self.entity_id},
            duration=duration,
        )

    def pause(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="pause",
            target={"entity_id": self.entity_id},
        )

    def cancel(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="cancel",
            target={"entity_id": self.entity_id},
        )

    def finish(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
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
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="change",
            target={"entity_id": self.entity_id},
            duration=duration,
        )


class TimerEntitySyncFacade(BaseEntitySyncFacade[TimerState, str]):
    def start(
        self,
        *,
        duration: dict[str, int] | None = None,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="start",
            target={"entity_id": self.entity.entity_id},
            duration=duration,
        )

    def pause(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="pause",
            target={"entity_id": self.entity.entity_id},
        )

    def cancel(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="cancel",
            target={"entity_id": self.entity.entity_id},
        )

    def finish(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="finish",
            target={"entity_id": self.entity.entity_id},
        )

    def change(
        self,
        *,
        duration: dict[str, int],
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="change",
            target={"entity_id": self.entity.entity_id},
            duration=duration,
        )
