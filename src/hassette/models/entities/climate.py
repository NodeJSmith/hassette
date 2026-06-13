from collections.abc import Coroutine
from typing import Any

from hassette.models.states import ClimateState
from hassette.models.states.climate import ClimateAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class ClimateEntity(BaseEntity[ClimateState, str]):
    @property
    def attributes(self) -> ClimateAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "ClimateEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(ClimateEntitySyncFacade)

    def set_preset_mode(
        self,
        *,
        preset_mode: str,
    ) -> Coroutine[Any, Any, None]:
        """Sets the preset mode of a thermostat.

        Args:
            preset_mode: Preset mode.
        """
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
        """Sets the target temperature of a thermostat.

        Args:
            hvac_mode: HVAC operation mode.
            target_temp_high: The max temperature setpoint.
            target_temp_low: The min temperature setpoint.
            temperature: The temperature setpoint.
        """
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
        """Sets the target humidity of a thermostat.

        Args:
            humidity: Target humidity.
        """
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
        """Sets the fan mode of a thermostat.

        Args:
            fan_mode: Fan operation mode.
        """
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
        """Sets the HVAC mode of a thermostat.

        Args:
            hvac_mode: HVAC operation mode.
        """
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
        """Sets the swing mode of a thermostat.

        Args:
            swing_mode: Swing operation mode.
        """
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
        """Sets the horizontal swing mode of a thermostat.

        Args:
            swing_horizontal_mode: Horizontal swing operation mode.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_swing_horizontal_mode",
            target={"entity_id": self.entity_id},
            swing_horizontal_mode=swing_horizontal_mode,
        )

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Turns on a thermostat."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Turns off a thermostat."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Toggles a thermostat on/off."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )


class ClimateEntitySyncFacade(BaseEntitySyncFacade[ClimateState, str]):
    """Synchronous facade for ClimateEntity service methods."""

    def set_preset_mode(
        self,
        *,
        preset_mode: str,
    ) -> None:
        """Sets the preset mode of a thermostat.

        Args:
            preset_mode: Preset mode.
        """
        self.entity.api.sync.call_service(
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
    ) -> None:
        """Sets the target temperature of a thermostat.

        Args:
            hvac_mode: HVAC operation mode.
            target_temp_high: The max temperature setpoint.
            target_temp_low: The min temperature setpoint.
            temperature: The temperature setpoint.
        """
        self.entity.api.sync.call_service(
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
    ) -> None:
        """Sets the target humidity of a thermostat.

        Args:
            humidity: Target humidity.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_humidity",
            target={"entity_id": self.entity.entity_id},
            humidity=humidity,
        )

    def set_fan_mode(
        self,
        *,
        fan_mode: str,
    ) -> None:
        """Sets the fan mode of a thermostat.

        Args:
            fan_mode: Fan operation mode.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_fan_mode",
            target={"entity_id": self.entity.entity_id},
            fan_mode=fan_mode,
        )

    def set_hvac_mode(
        self,
        *,
        hvac_mode: str | None = None,
    ) -> None:
        """Sets the HVAC mode of a thermostat.

        Args:
            hvac_mode: HVAC operation mode.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_hvac_mode",
            target={"entity_id": self.entity.entity_id},
            hvac_mode=hvac_mode,
        )

    def set_swing_mode(
        self,
        *,
        swing_mode: str,
    ) -> None:
        """Sets the swing mode of a thermostat.

        Args:
            swing_mode: Swing operation mode.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_swing_mode",
            target={"entity_id": self.entity.entity_id},
            swing_mode=swing_mode,
        )

    def set_swing_horizontal_mode(
        self,
        *,
        swing_horizontal_mode: str,
    ) -> None:
        """Sets the horizontal swing mode of a thermostat.

        Args:
            swing_horizontal_mode: Horizontal swing operation mode.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_swing_horizontal_mode",
            target={"entity_id": self.entity.entity_id},
            swing_horizontal_mode=swing_horizontal_mode,
        )

    def turn_on(self) -> None:
        """Turns on a thermostat."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Turns off a thermostat."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self) -> None:
        """Toggles a thermostat on/off."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )
