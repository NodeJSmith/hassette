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
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(SelectEntitySyncFacade)

    def select_first(self) -> Coroutine[Any, Any, None]:
        """Selects the first option of a select."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="select_first",
            target={"entity_id": self.entity_id},
        )

    def select_last(self) -> Coroutine[Any, Any, None]:
        """Selects the last option of a select."""
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
        """Selects the next option of a select.

        Args:
            cycle: If the option should cycle from the last to the first.
        """
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
        """Selects an option of a select.

        Args:
            option: Option to be selected.
        """
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
        """Selects the previous option of a select.

        Args:
            cycle: If the option should cycle from the first to the last.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="select_previous",
            target={"entity_id": self.entity_id},
            cycle=cycle,
        )


class SelectEntitySyncFacade(BaseEntitySyncFacade[SelectState, str]):
    """Synchronous facade for SelectEntity service methods."""

    def select_first(self) -> None:
        """Selects the first option of a select."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_first",
            target={"entity_id": self.entity.entity_id},
        )

    def select_last(self) -> None:
        """Selects the last option of a select."""
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
        """Selects the next option of a select.

        Args:
            cycle: If the option should cycle from the last to the first.
        """
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
        """Selects an option of a select.

        Args:
            option: Option to be selected.
        """
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
        """Selects the previous option of a select.

        Args:
            cycle: If the option should cycle from the first to the last.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_previous",
            target={"entity_id": self.entity.entity_id},
            cycle=cycle,
        )
