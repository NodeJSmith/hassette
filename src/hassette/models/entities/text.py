from collections.abc import Coroutine
from typing import Any

from hassette.models.states import TextState
from hassette.models.states.text import TextAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class TextEntity(BaseEntity[TextState, str]):
    @property
    def attributes(self) -> TextAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "TextEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(TextEntitySyncFacade)

    def set_value(
        self,
        *,
        value: str,
    ) -> Coroutine[Any, Any, None]:
        """Sets the value of a text entity.

        Args:
            value: Enter your text.
        """
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            value=value,
        )


class TextEntitySyncFacade(BaseEntitySyncFacade[TextState, str]):
    """Synchronous facade for TextEntity service methods."""

    def set_value(
        self,
        *,
        value: str,
    ) -> None:
        """Sets the value of a text entity.

        Args:
            value: Enter your text.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            value=value,
        )
