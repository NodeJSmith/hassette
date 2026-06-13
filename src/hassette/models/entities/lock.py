from collections.abc import Coroutine
from typing import Any

from hassette.models.states import LockState
from hassette.models.states.lock import LockAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class LockEntity(BaseEntity[LockState, str]):
    @property
    def attributes(self) -> LockAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "LockEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(LockEntitySyncFacade)

    def lock(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Locks a lock.

        Args:
            code: Code used to lock the lock.
        """
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
        """Opens a lock.

        Args:
            code: Code used to open the lock.
        """
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
        """Unlocks a lock.

        Args:
            code: Code used to unlock the lock.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="unlock",
            target={"entity_id": self.entity_id},
            code=code,
        )


class LockEntitySyncFacade(BaseEntitySyncFacade[LockState, str]):
    """Synchronous facade for LockEntity service methods."""

    def lock(
        self,
        *,
        code: str | None = None,
    ) -> None:
        """Locks a lock.

        Args:
            code: Code used to lock the lock.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="lock",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )

    def open(
        self,
        *,
        code: str | None = None,
    ) -> None:
        """Opens a lock.

        Args:
            code: Code used to open the lock.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="open",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )

    def unlock(
        self,
        *,
        code: str | None = None,
    ) -> None:
        """Unlocks a lock.

        Args:
            code: Code used to unlock the lock.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="unlock",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )
