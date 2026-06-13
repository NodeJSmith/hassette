from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import LockState
from hassette.models.states.lock import LockAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class LockEntity(BaseEntity[LockState, str]):
    @property
    def attributes(self) -> LockAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "LockEntitySyncFacade":
        if self._sync is None:
            self._sync = LockEntitySyncFacade(entity=self)
        return cast("LockEntitySyncFacade", self._sync)

    def lock(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="lock",
            target={"entity_id": self.entity_id},
            code=code,
        )

    def open(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="open",
            target={"entity_id": self.entity_id},
            code=code,
        )

    def unlock(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="unlock",
            target={"entity_id": self.entity_id},
            code=code,
        )


class LockEntitySyncFacade(BaseEntitySyncFacade[LockState, str]):
    def lock(
        self,
        *,
        code: str | None = None,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="lock",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )

    def open(
        self,
        *,
        code: str | None = None,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="open",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )

    def unlock(
        self,
        *,
        code: str | None = None,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="unlock",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )
