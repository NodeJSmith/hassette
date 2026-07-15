from collections.abc import Coroutine
from typing import Any

from hassette.models.states import AutomationState
from hassette.models.states.automation import AutomationAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class AutomationEntity(BaseEntity[AutomationState, str]):
    @property
    def attributes(self) -> AutomationAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "AutomationEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(AutomationEntitySyncFacade)

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Enables an automation."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(
        self,
        *,
        stop_actions: bool | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Disables an automation.

        Args:
            stop_actions: Stops currently running actions.
        """
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
            stop_actions=stop_actions,
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Toggles (enable / disable) an automation."""
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    def trigger(
        self,
        *,
        skip_condition: bool | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Triggers the actions of an automation.

        Args:
            skip_condition: Defines whether or not the conditions will be skipped.
        """
        return self.api.call_service(
            domain=self.domain,
            service="trigger",
            target={"entity_id": self.entity_id},
            skip_condition=skip_condition,
        )


class AutomationEntitySyncFacade(BaseEntitySyncFacade[AutomationState, str]):
    """Synchronous facade for AutomationEntity service methods."""

    def turn_on(self) -> None:
        """Enables an automation."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(
        self,
        *,
        stop_actions: bool | None = None,
    ) -> None:
        """Disables an automation.

        Args:
            stop_actions: Stops currently running actions.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
            stop_actions=stop_actions,
        )

    def toggle(self) -> None:
        """Toggles (enable / disable) an automation."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )

    def trigger(
        self,
        *,
        skip_condition: bool | None = None,
    ) -> None:
        """Triggers the actions of an automation.

        Args:
            skip_condition: Defines whether or not the conditions will be skipped.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="trigger",
            target={"entity_id": self.entity.entity_id},
            skip_condition=skip_condition,
        )
