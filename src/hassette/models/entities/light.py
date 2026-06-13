from collections.abc import Coroutine
from typing import Any, Literal

from hassette.const.colors import Color
from hassette.models.states import LightState
from hassette.models.states.light import LightAttributes

from .base import BaseEntity, BaseEntitySyncFacade

Flash = Literal["long", "short"]


class LightEntity(BaseEntity[LightState, str]):
    @property
    def attributes(self) -> LightAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "LightEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(LightEntitySyncFacade)

    def turn_on(
        self,
        *,
        brightness: int | None = None,
        brightness_pct: int | None = None,
        brightness_step: int | None = None,
        brightness_step_pct: int | None = None,
        color_name: Color | None = None,
        color_temp_kelvin: int | None = None,
        effect: str | None = None,
        flash: Flash | None = None,
        hs_color: Any | None = None,
        profile: str | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: Any | None = None,
        rgbww_color: Any | None = None,
        transition: int | None = None,
        white: Any | None = None,
        xy_color: Any | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the light.turn_on service.

        Args:
            brightness: Number indicating brightness, where 0 turns the light off, 1 is the minimum brightness, and 255
                is the maximum brightness.
            brightness_pct: Number indicating the percentage of full brightness, where 0 turns the light off, 1 is the
                minimum brightness, and 100 is the maximum brightness.
            brightness_step: Change brightness by an amount.
            brightness_step_pct: Change brightness by a percentage.
            color_name: A human-readable color name.
            color_temp_kelvin: Color temperature in Kelvin.
            effect: Light effect.
            flash: Tell light to flash, can be either value short or long.
            hs_color: Color in hue/sat format. A list of two integers. Hue is 0-360 and Sat is 0-100.
            profile: Name of a light profile to use.
            rgb_color: The color in RGB format. A list of three integers between 0 and 255 representing the values of
                red, green, and blue.
            rgbw_color: The color in RGBW format. A list of four integers between 0 and 255 representing the values of
                red, green, blue, and white.
            rgbww_color: The color in RGBWW format. A list of five integers between 0 and 255 representing the values of
                red, green, blue, cold white, and warm white.
            transition: Duration it takes to get to next state.
            white: Set the light to white mode.
            xy_color: Color in XY-format. A list of two decimal numbers between 0 and 1.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
            brightness=brightness,
            brightness_pct=brightness_pct,
            brightness_step=brightness_step,
            brightness_step_pct=brightness_step_pct,
            color_name=color_name,
            color_temp_kelvin=color_temp_kelvin,
            effect=effect,
            flash=flash,
            hs_color=hs_color,
            profile=profile,
            rgb_color=rgb_color,
            rgbw_color=rgbw_color,
            rgbww_color=rgbww_color,
            transition=transition,
            white=white,
            xy_color=xy_color,
        )

    def turn_off(
        self,
        *,
        flash: Literal["long", "short"] | None = None,
        transition: int | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the light.turn_off service.

        Args:
            flash: Tell light to flash, can be either value short or long.
            transition: Duration it takes to get to next state.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
            flash=flash,
            transition=transition,
        )

    def toggle(
        self,
        *,
        brightness: int | None = None,
        brightness_pct: int | None = None,
        color_name: Color | None = None,
        color_temp_kelvin: int | None = None,
        effect: str | None = None,
        flash: Literal["long", "short"] | None = None,
        hs_color: Any | None = None,
        profile: str | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: Any | None = None,
        rgbww_color: Any | None = None,
        transition: int | None = None,
        white: Any | None = None,
        xy_color: Any | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the light.toggle service.

        Args:
            brightness: Number indicating brightness, where 0 turns the light off, 1 is the minimum brightness, and 255
                is the maximum brightness.
            brightness_pct: Number indicating the percentage of full brightness, where 0 turns the light off, 1 is the
                minimum brightness, and 100 is the maximum brightness.
            color_name: A human-readable color name.
            color_temp_kelvin: Color temperature in Kelvin.
            effect: Light effect.
            flash: Tell light to flash, can be either value short or long.
            hs_color: Color in hue/sat format. A list of two integers. Hue is 0-360 and Sat is 0-100.
            profile: Name of a light profile to use.
            rgb_color: The color in RGB format. A list of three integers between 0 and 255 representing the values of
                red, green, and blue.
            rgbw_color: The color in RGBW format. A list of four integers between 0 and 255 representing the values of
                red, green, blue, and white.
            rgbww_color: The color in RGBWW format. A list of five integers between 0 and 255 representing the values of
                red, green, blue, cold white, and warm white.
            transition: Duration it takes to get to next state.
            white: Set the light to white mode.
            xy_color: Color in XY-format. A list of two decimal numbers between 0 and 1.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
            brightness=brightness,
            brightness_pct=brightness_pct,
            color_name=color_name,
            color_temp_kelvin=color_temp_kelvin,
            effect=effect,
            flash=flash,
            hs_color=hs_color,
            profile=profile,
            rgb_color=rgb_color,
            rgbw_color=rgbw_color,
            rgbww_color=rgbww_color,
            transition=transition,
            white=white,
            xy_color=xy_color,
        )


class LightEntitySyncFacade(BaseEntitySyncFacade[LightState, str]):
    """Synchronous facade for LightEntity service methods."""

    def turn_on(
        self,
        *,
        brightness: int | None = None,
        brightness_pct: int | None = None,
        brightness_step: int | None = None,
        brightness_step_pct: int | None = None,
        color_name: Color | None = None,
        color_temp_kelvin: int | None = None,
        effect: str | None = None,
        flash: Flash | None = None,
        hs_color: Any | None = None,
        profile: str | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: Any | None = None,
        rgbww_color: Any | None = None,
        transition: int | None = None,
        white: Any | None = None,
        xy_color: Any | None = None,
    ) -> None:
        """Call the light.turn_on service synchronously.

        Args:
            brightness: Number indicating brightness, where 0 turns the light off, 1 is the minimum brightness, and 255
                is the maximum brightness.
            brightness_pct: Number indicating the percentage of full brightness, where 0 turns the light off, 1 is the
                minimum brightness, and 100 is the maximum brightness.
            brightness_step: Change brightness by an amount.
            brightness_step_pct: Change brightness by a percentage.
            color_name: A human-readable color name.
            color_temp_kelvin: Color temperature in Kelvin.
            effect: Light effect.
            flash: Tell light to flash, can be either value short or long.
            hs_color: Color in hue/sat format. A list of two integers. Hue is 0-360 and Sat is 0-100.
            profile: Name of a light profile to use.
            rgb_color: The color in RGB format. A list of three integers between 0 and 255 representing the values of
                red, green, and blue.
            rgbw_color: The color in RGBW format. A list of four integers between 0 and 255 representing the values of
                red, green, blue, and white.
            rgbww_color: The color in RGBWW format. A list of five integers between 0 and 255 representing the values of
                red, green, blue, cold white, and warm white.
            transition: Duration it takes to get to next state.
            white: Set the light to white mode.
            xy_color: Color in XY-format. A list of two decimal numbers between 0 and 1.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
            brightness=brightness,
            brightness_pct=brightness_pct,
            brightness_step=brightness_step,
            brightness_step_pct=brightness_step_pct,
            color_name=color_name,
            color_temp_kelvin=color_temp_kelvin,
            effect=effect,
            flash=flash,
            hs_color=hs_color,
            profile=profile,
            rgb_color=rgb_color,
            rgbw_color=rgbw_color,
            rgbww_color=rgbww_color,
            transition=transition,
            white=white,
            xy_color=xy_color,
        )

    def turn_off(
        self,
        *,
        flash: Literal["long", "short"] | None = None,
        transition: int | None = None,
    ) -> None:
        """Call the light.turn_off service synchronously.

        Args:
            flash: Tell light to flash, can be either value short or long.
            transition: Duration it takes to get to next state.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
            flash=flash,
            transition=transition,
        )

    def toggle(
        self,
        *,
        brightness: int | None = None,
        brightness_pct: int | None = None,
        color_name: Color | None = None,
        color_temp_kelvin: int | None = None,
        effect: str | None = None,
        flash: Literal["long", "short"] | None = None,
        hs_color: Any | None = None,
        profile: str | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: Any | None = None,
        rgbww_color: Any | None = None,
        transition: int | None = None,
        white: Any | None = None,
        xy_color: Any | None = None,
    ) -> None:
        """Call the light.toggle service synchronously.

        Args:
            brightness: Number indicating brightness, where 0 turns the light off, 1 is the minimum brightness, and 255
                is the maximum brightness.
            brightness_pct: Number indicating the percentage of full brightness, where 0 turns the light off, 1 is the
                minimum brightness, and 100 is the maximum brightness.
            color_name: A human-readable color name.
            color_temp_kelvin: Color temperature in Kelvin.
            effect: Light effect.
            flash: Tell light to flash, can be either value short or long.
            hs_color: Color in hue/sat format. A list of two integers. Hue is 0-360 and Sat is 0-100.
            profile: Name of a light profile to use.
            rgb_color: The color in RGB format. A list of three integers between 0 and 255 representing the values of
                red, green, and blue.
            rgbw_color: The color in RGBW format. A list of four integers between 0 and 255 representing the values of
                red, green, blue, and white.
            rgbww_color: The color in RGBWW format. A list of five integers between 0 and 255 representing the values of
                red, green, blue, cold white, and warm white.
            transition: Duration it takes to get to next state.
            white: Set the light to white mode.
            xy_color: Color in XY-format. A list of two decimal numbers between 0 and 1.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
            brightness=brightness,
            brightness_pct=brightness_pct,
            color_name=color_name,
            color_temp_kelvin=color_temp_kelvin,
            effect=effect,
            flash=flash,
            hs_color=hs_color,
            profile=profile,
            rgb_color=rgb_color,
            rgbw_color=rgbw_color,
            rgbww_color=rgbww_color,
            transition=transition,
            white=white,
            xy_color=xy_color,
        )
