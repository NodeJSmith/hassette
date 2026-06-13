from collections.abc import Coroutine
from typing import Any

from hassette.models.states import UpdateState
from hassette.models.states.update import UpdateAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class UpdateEntity(BaseEntity[UpdateState, str]):
    @property
    def attributes(self) -> UpdateAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "UpdateEntitySyncFacade":
        return self._get_or_create_sync(UpdateEntitySyncFacade)

    def install(
        self,
        *,
        backup: bool | None = None,
        version: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="install",
            target={"entity_id": self.entity_id},
            backup=backup,
            version=version,
        )

    def skip(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="skip",
            target={"entity_id": self.entity_id},
        )

    def clear_skipped(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="clear_skipped",
            target={"entity_id": self.entity_id},
        )


class UpdateEntitySyncFacade(BaseEntitySyncFacade[UpdateState, str]):
    def install(
        self,
        *,
        backup: bool | None = None,
        version: str | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="install",
            target={"entity_id": self.entity.entity_id},
            backup=backup,
            version=version,
        )

    def skip(self) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="skip",
            target={"entity_id": self.entity.entity_id},
        )

    def clear_skipped(self) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="clear_skipped",
            target={"entity_id": self.entity.entity_id},
        )
