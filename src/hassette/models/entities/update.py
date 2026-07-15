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
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(UpdateEntitySyncFacade)

    def install(
        self,
        *,
        backup: bool | None = None,
        version: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Installs an update for a device or service.

        Args:
            backup: If supported by the integration, this creates a backup before starting the update.
            version: The version to install. If omitted, the latest version will be installed.
        """
        return self.api.call_service(
            domain=self.domain,
            service="install",
            target={"entity_id": self.entity_id},
            backup=backup,
            version=version,
        )

    def skip(self) -> Coroutine[Any, Any, None]:
        """Marks a currently available update as skipped."""
        return self.api.call_service(
            domain=self.domain,
            service="skip",
            target={"entity_id": self.entity_id},
        )

    def clear_skipped(self) -> Coroutine[Any, Any, None]:
        """Removes the skipped version marker from an update."""
        return self.api.call_service(
            domain=self.domain,
            service="clear_skipped",
            target={"entity_id": self.entity_id},
        )


class UpdateEntitySyncFacade(BaseEntitySyncFacade[UpdateState, str]):
    """Synchronous facade for UpdateEntity service methods."""

    def install(
        self,
        *,
        backup: bool | None = None,
        version: str | None = None,
    ) -> None:
        """Installs an update for a device or service.

        Args:
            backup: If supported by the integration, this creates a backup before starting the update.
            version: The version to install. If omitted, the latest version will be installed.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="install",
            target={"entity_id": self.entity.entity_id},
            backup=backup,
            version=version,
        )

    def skip(self) -> None:
        """Marks a currently available update as skipped."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="skip",
            target={"entity_id": self.entity.entity_id},
        )

    def clear_skipped(self) -> None:
        """Removes the skipped version marker from an update."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="clear_skipped",
            target={"entity_id": self.entity.entity_id},
        )
