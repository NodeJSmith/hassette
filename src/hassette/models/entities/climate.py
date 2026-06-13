from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import ClimateState
from hassette.models.states.climate import ClimateAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class ClimateEntity(BaseEntity[ClimateState, str]):
    @property
    def attributes(self) -> ClimateAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "ClimateEntitySyncFacade":
        if self._sync is None:
            self._sync = ClimateEntitySyncFacade(entity=self)
        return cast("ClimateEntitySyncFacade", self._sync)

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

    def set_temperature(
        self,
        *,
        hvac_mode: str | None = None,
        target_temp_high: float | None = None,
        target_temp_low: float | None = None,
        temperature: float | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_temperature",
            target={"entity_id": self.entity_id},
            hvac_mode=hvac_mode,
            target_temp_high=target_temp_high,
            target_temp_low=target_temp_low,
            temperature=temperature,
        )

    def set_humidity(
        self,
        *,
        humidity: int,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_humidity",
            target={"entity_id": self.entity_id},
            humidity=humidity,
        )

    def set_fan_mode(
        self,
        *,
        fan_mode: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_fan_mode",
            target={"entity_id": self.entity_id},
            fan_mode=fan_mode,
        )

    def set_hvac_mode(
        self,
        *,
        hvac_mode: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_hvac_mode",
            target={"entity_id": self.entity_id},
            hvac_mode=hvac_mode,
        )

    def set_swing_mode(
        self,
        *,
        swing_mode: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_swing_mode",
            target={"entity_id": self.entity_id},
            swing_mode=swing_mode,
        )

    def set_swing_horizontal_mode(
        self,
        *,
        swing_horizontal_mode: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_swing_horizontal_mode",
            target={"entity_id": self.entity_id},
            swing_horizontal_mode=swing_horizontal_mode,
        )

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
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


class ClimateEntitySyncFacade(BaseEntitySyncFacade[ClimateState, str]):
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

    def set_temperature(
        self,
        *,
        hvac_mode: str | None = None,
        target_temp_high: float | None = None,
        target_temp_low: float | None = None,
        temperature: float | None = None,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_temperature",
            target={"entity_id": self.entity.entity_id},
            hvac_mode=hvac_mode,
            target_temp_high=target_temp_high,
            target_temp_low=target_temp_low,
            temperature=temperature,
        )

    def set_humidity(
        self,
        *,
        humidity: int,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_humidity",
            target={"entity_id": self.entity.entity_id},
            humidity=humidity,
        )

    def set_fan_mode(
        self,
        *,
        fan_mode: str,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_fan_mode",
            target={"entity_id": self.entity.entity_id},
            fan_mode=fan_mode,
        )

    def set_hvac_mode(
        self,
        *,
        hvac_mode: str | None = None,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_hvac_mode",
            target={"entity_id": self.entity.entity_id},
            hvac_mode=hvac_mode,
        )

    def set_swing_mode(
        self,
        *,
        swing_mode: str,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_swing_mode",
            target={"entity_id": self.entity.entity_id},
            swing_mode=swing_mode,
        )

    def set_swing_horizontal_mode(
        self,
        *,
        swing_horizontal_mode: str,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_swing_horizontal_mode",
            target={"entity_id": self.entity.entity_id},
            swing_horizontal_mode=swing_horizontal_mode,
        )

    def turn_on(self):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )
