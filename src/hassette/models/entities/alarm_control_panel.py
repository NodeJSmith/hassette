from collections.abc import Coroutine
from typing import Any

from hassette.models.states import AlarmControlPanelState
from hassette.models.states.alarm_control_panel import AlarmControlPanelAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class AlarmControlPanelEntity(BaseEntity[AlarmControlPanelState, str]):
    @property
    def attributes(self) -> AlarmControlPanelAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "AlarmControlPanelEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(AlarmControlPanelEntitySyncFacade)

    def alarm_disarm(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="alarm_disarm",
            target={"entity_id": self.entity_id},
            code=code,
        )

    def alarm_arm_custom_bypass(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="alarm_arm_custom_bypass",
            target={"entity_id": self.entity_id},
            code=code,
        )

    def alarm_arm_home(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="alarm_arm_home",
            target={"entity_id": self.entity_id},
            code=code,
        )

    def alarm_arm_away(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="alarm_arm_away",
            target={"entity_id": self.entity_id},
            code=code,
        )

    def alarm_arm_night(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="alarm_arm_night",
            target={"entity_id": self.entity_id},
            code=code,
        )

    def alarm_arm_vacation(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="alarm_arm_vacation",
            target={"entity_id": self.entity_id},
            code=code,
        )

    def alarm_trigger(
        self,
        *,
        code: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="alarm_trigger",
            target={"entity_id": self.entity_id},
            code=code,
        )


class AlarmControlPanelEntitySyncFacade(BaseEntitySyncFacade[AlarmControlPanelState, str]):
    """Synchronous facade for AlarmControlPanelEntity service methods."""

    def alarm_disarm(
        self,
        *,
        code: str | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="alarm_disarm",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )

    def alarm_arm_custom_bypass(
        self,
        *,
        code: str | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="alarm_arm_custom_bypass",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )

    def alarm_arm_home(
        self,
        *,
        code: str | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="alarm_arm_home",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )

    def alarm_arm_away(
        self,
        *,
        code: str | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="alarm_arm_away",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )

    def alarm_arm_night(
        self,
        *,
        code: str | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="alarm_arm_night",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )

    def alarm_arm_vacation(
        self,
        *,
        code: str | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="alarm_arm_vacation",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )

    def alarm_trigger(
        self,
        *,
        code: str | None = None,
    ) -> None:
        """Runs synchronously — blocks until the service call completes."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="alarm_trigger",
            target={"entity_id": self.entity.entity_id},
            code=code,
        )
