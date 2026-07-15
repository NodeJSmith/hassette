from collections.abc import Coroutine
from typing import Any, Literal

from hassette.models.states import FanState
from hassette.models.states.fan import FanAttributes

from .base import BaseEntity, BaseEntitySyncFacade

FanDirection = Literal["forward", "reverse"]


class FanEntity(BaseEntity[FanState, str]):
    @property
    def attributes(self) -> FanAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "FanEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(FanEntitySyncFacade)

    def set_preset_mode(
        self,
        *,
        preset_mode: str,
    ) -> Coroutine[Any, Any, None]:
        """Sets the preset mode of a fan.

        Args:
            preset_mode: Preset fan mode.
        """
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
        """Sets the speed of a fan.

        Args:
            percentage: Speed of the fan.
        """
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
        """Turns on a fan.

        Args:
            percentage: Speed of the fan.
            preset_mode: Preset fan mode.
        """
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
            percentage=percentage,
            preset_mode=preset_mode,
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Turns off a fan."""
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
        """Controls the oscillation of a fan.

        Args:
            oscillating: Turns oscillation on/off.
        """
        return self.api.call_service(
            domain=self.domain,
            service="oscillate",
            target={"entity_id": self.entity_id},
            oscillating=oscillating,
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Toggles a fan on/off."""
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    def set_direction(
        self,
        *,
        direction: FanDirection,
    ) -> Coroutine[Any, Any, None]:
        """Sets a fan's rotation direction.

        Args:
            direction: Direction of the fan rotation.
        """
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
        """Increases the speed of a fan.

        Args:
            percentage_step: Percentage step by which the speed should be increased.
        """
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
        """Decreases the speed of a fan.

        Args:
            percentage_step: Percentage step by which the speed should be decreased.
        """
        return self.api.call_service(
            domain=self.domain,
            service="decrease_speed",
            target={"entity_id": self.entity_id},
            percentage_step=percentage_step,
        )


class FanEntitySyncFacade(BaseEntitySyncFacade[FanState, str]):
    """Synchronous facade for FanEntity service methods."""

    def set_preset_mode(
        self,
        *,
        preset_mode: str,
    ) -> None:
        """Sets the preset mode of a fan.

        Args:
            preset_mode: Preset fan mode.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_preset_mode",
            target={"entity_id": self.entity.entity_id},
            preset_mode=preset_mode,
        )

    def set_percentage(
        self,
        *,
        percentage: int,
    ) -> None:
        """Sets the speed of a fan.

        Args:
            percentage: Speed of the fan.
        """
        self.entity.api.sync.call_service(
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
    ) -> None:
        """Turns on a fan.

        Args:
            percentage: Speed of the fan.
            preset_mode: Preset fan mode.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
            percentage=percentage,
            preset_mode=preset_mode,
        )

    def turn_off(self) -> None:
        """Turns off a fan."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def oscillate(
        self,
        *,
        oscillating: bool,
    ) -> None:
        """Controls the oscillation of a fan.

        Args:
            oscillating: Turns oscillation on/off.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="oscillate",
            target={"entity_id": self.entity.entity_id},
            oscillating=oscillating,
        )

    def toggle(self) -> None:
        """Toggles a fan on/off."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )

    def set_direction(
        self,
        *,
        direction: FanDirection,
    ) -> None:
        """Sets a fan's rotation direction.

        Args:
            direction: Direction of the fan rotation.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_direction",
            target={"entity_id": self.entity.entity_id},
            direction=direction,
        )

    def increase_speed(
        self,
        *,
        percentage_step: int | None = None,
    ) -> None:
        """Increases the speed of a fan.

        Args:
            percentage_step: Percentage step by which the speed should be increased.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="increase_speed",
            target={"entity_id": self.entity.entity_id},
            percentage_step=percentage_step,
        )

    def decrease_speed(
        self,
        *,
        percentage_step: int | None = None,
    ) -> None:
        """Decreases the speed of a fan.

        Args:
            percentage_step: Percentage step by which the speed should be decreased.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="decrease_speed",
            target={"entity_id": self.entity.entity_id},
            percentage_step=percentage_step,
        )
