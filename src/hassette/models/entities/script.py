from collections.abc import Coroutine
from typing import Any

from hassette.models.states import ScriptState
from hassette.models.states.script import ScriptAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class ScriptEntity(BaseEntity[ScriptState, str]):
    @property
    def attributes(self) -> ScriptAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "ScriptEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(ScriptEntitySyncFacade)

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Runs the sequence of actions defined in a script."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Stops a running script."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Starts a script if it isn't running, stops it otherwise."""
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )


class ScriptEntitySyncFacade(BaseEntitySyncFacade[ScriptState, str]):
    """Synchronous facade for ScriptEntity service methods."""

    def turn_on(self) -> None:
        """Runs the sequence of actions defined in a script."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Stops a running script."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self) -> None:
        """Starts a script if it isn't running, stops it otherwise."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )
