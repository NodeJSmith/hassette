from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import CoverState
from hassette.models.states.cover import CoverAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class CoverEntity(BaseEntity[CoverState, str]):
    @property
    def attributes(self) -> CoverAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "CoverEntitySyncFacade":
        if self._sync is None:
            self._sync = CoverEntitySyncFacade(entity=self)
        return cast("CoverEntitySyncFacade", self._sync)

    def open_cover(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="open_cover",
            target={"entity_id": self.entity_id},
        )

    def close_cover(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="close_cover",
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

    def set_cover_position(
        self,
        *,
        position: int,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_cover_position",
            target={"entity_id": self.entity_id},
            position=position,
        )

    def stop_cover(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="stop_cover",
            target={"entity_id": self.entity_id},
        )

    def open_cover_tilt(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="open_cover_tilt",
            target={"entity_id": self.entity_id},
        )

    def close_cover_tilt(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="close_cover_tilt",
            target={"entity_id": self.entity_id},
        )

    def toggle_cover_tilt(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle_cover_tilt",
            target={"entity_id": self.entity_id},
        )

    def set_cover_tilt_position(
        self,
        *,
        tilt_position: int,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_cover_tilt_position",
            target={"entity_id": self.entity_id},
            tilt_position=tilt_position,
        )

    def stop_cover_tilt(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="stop_cover_tilt",
            target={"entity_id": self.entity_id},
        )


class CoverEntitySyncFacade(BaseEntitySyncFacade[CoverState, str]):
    def open_cover(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="open_cover",
            target={"entity_id": self.entity.entity_id},
        )

    def close_cover(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="close_cover",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )

    def set_cover_position(
        self,
        *,
        position: int,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_cover_position",
            target={"entity_id": self.entity.entity_id},
            position=position,
        )

    def stop_cover(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="stop_cover",
            target={"entity_id": self.entity.entity_id},
        )

    def open_cover_tilt(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="open_cover_tilt",
            target={"entity_id": self.entity.entity_id},
        )

    def close_cover_tilt(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="close_cover_tilt",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle_cover_tilt(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle_cover_tilt",
            target={"entity_id": self.entity.entity_id},
        )

    def set_cover_tilt_position(
        self,
        *,
        tilt_position: int,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_cover_tilt_position",
            target={"entity_id": self.entity.entity_id},
            tilt_position=tilt_position,
        )

    def stop_cover_tilt(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="stop_cover_tilt",
            target={"entity_id": self.entity.entity_id},
        )
