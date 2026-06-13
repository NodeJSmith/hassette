from collections.abc import Coroutine
from typing import Any

from hassette.models.states import SelectState
from hassette.models.states.select import SelectAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class SelectEntity(BaseEntity[SelectState, str]):
    @property
    def attributes(self) -> SelectAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "SelectEntitySyncFacade":
        return self._get_or_create_sync(SelectEntitySyncFacade)

    def select_first(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="select_first",
            target={"entity_id": self.entity_id},
        )

    def select_last(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="select_last",
            target={"entity_id": self.entity_id},
        )

    def select_next(
        self,
        *,
        cycle: bool | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="select_next",
            target={"entity_id": self.entity_id},
            cycle=cycle,
        )

    def select_option(
        self,
        *,
        option: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="select_option",
            target={"entity_id": self.entity_id},
            option=option,
        )

    def select_previous(
        self,
        *,
        cycle: bool | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="select_previous",
            target={"entity_id": self.entity_id},
            cycle=cycle,
        )


class SelectEntitySyncFacade(BaseEntitySyncFacade[SelectState, str]):
    def select_first(self) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_first",
            target={"entity_id": self.entity.entity_id},
        )

    def select_last(self) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_last",
            target={"entity_id": self.entity.entity_id},
        )

    def select_next(
        self,
        *,
        cycle: bool | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_next",
            target={"entity_id": self.entity.entity_id},
            cycle=cycle,
        )

    def select_option(
        self,
        *,
        option: str,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_option",
            target={"entity_id": self.entity.entity_id},
            option=option,
        )

    def select_previous(
        self,
        *,
        cycle: bool | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_previous",
            target={"entity_id": self.entity.entity_id},
            cycle=cycle,
        )
