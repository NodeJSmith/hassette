from collections.abc import Coroutine
from typing import Any, Literal, cast

from hassette.models.states import FanState
from hassette.models.states.fan import FanAttributes

from .base import BaseEntity, BaseEntitySyncFacade

Direction = Literal["forward", "reverse"]


class FanEntity(BaseEntity[FanState, str]):
    @property
    def attributes(self) -> FanAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "FanEntitySyncFacade":
        if self._sync is None:
            self._sync = FanEntitySyncFacade(entity=self)
        return cast("FanEntitySyncFacade", self._sync)

    def set_preset_mode(
        self,
        *,
        preset_mode: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_preset_mode",
            target={"entity_id": self.entity_id},
            preset_mode=preset_mode,
        )

    def set_percentage(
        self,
        *,
        percentage: int,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_percentage",
            target={"entity_id": self.entity_id},
            percentage=percentage,
        )

    def turn_on(
        self,
        *,
        percentage: int | None = None,
        preset_mode: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
            percentage=percentage,
            preset_mode=preset_mode,
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

    def oscillate(
        self,
        *,
        oscillating: bool,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="oscillate",
            target={"entity_id": self.entity_id},
            oscillating=oscillating,
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

    def set_direction(
        self,
        *,
        direction: Direction,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_direction",
            target={"entity_id": self.entity_id},
            direction=direction,
        )

    def increase_speed(
        self,
        *,
        percentage_step: int | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="increase_speed",
            target={"entity_id": self.entity_id},
            percentage_step=percentage_step,
        )

    def decrease_speed(
        self,
        *,
        percentage_step: int | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="decrease_speed",
            target={"entity_id": self.entity_id},
            percentage_step=percentage_step,
        )


class FanEntitySyncFacade(BaseEntitySyncFacade[FanState, str]):
    def set_preset_mode(
        self,
        *,
        preset_mode: str,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_preset_mode",
            target={"entity_id": self.entity.entity_id},
            preset_mode=preset_mode,
        )

    def set_percentage(
        self,
        *,
        percentage: int,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_percentage",
            target={"entity_id": self.entity.entity_id},
            percentage=percentage,
        )

    def turn_on(
        self,
        *,
        percentage: int | None = None,
        preset_mode: str | None = None,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
            percentage=percentage,
            preset_mode=preset_mode,
        )

    def turn_off(self):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def oscillate(
        self,
        *,
        oscillating: bool,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="oscillate",
            target={"entity_id": self.entity.entity_id},
            oscillating=oscillating,
        )

    def toggle(self):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )

    def set_direction(
        self,
        *,
        direction: Direction,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_direction",
            target={"entity_id": self.entity.entity_id},
            direction=direction,
        )

    def increase_speed(
        self,
        *,
        percentage_step: int | None = None,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="increase_speed",
            target={"entity_id": self.entity.entity_id},
            percentage_step=percentage_step,
        )

    def decrease_speed(
        self,
        *,
        percentage_step: int | None = None,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="decrease_speed",
            target={"entity_id": self.entity.entity_id},
            percentage_step=percentage_step,
        )
