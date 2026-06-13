from collections.abc import Coroutine
from typing import Any

from hassette.models.states import SirenState
from hassette.models.states.siren import SirenAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class SirenEntity(BaseEntity[SirenState, str]):
    @property
    def attributes(self) -> SirenAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "SirenEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(SirenEntitySyncFacade)

    def turn_on(
        self,
        *,
        duration: str | None = None,
        tone: str | None = None,
        volume_level: float | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
            duration=duration,
            tone=tone,
            volume_level=volume_level,
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )


class SirenEntitySyncFacade(BaseEntitySyncFacade[SirenState, str]):
    """Synchronous facade for SirenEntity service methods."""

    def turn_on(
        self,
        *,
        duration: str | None = None,
        tone: str | None = None,
        volume_level: float | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
            duration=duration,
            tone=tone,
            volume_level=volume_level,
        )

    def turn_off(self) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )
