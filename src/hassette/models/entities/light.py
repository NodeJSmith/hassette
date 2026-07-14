from collections.abc import Coroutine
from typing import Any, Literal

from hassette.const.colors import Color
from hassette.models.states import LightState
from hassette.models.states.light import LightAttributes

from .base import BaseEntity, BaseEntitySyncFacade

LightFlash = Literal["long", "short"]


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
        flash: LightFlash | None = None,
        hs_color: tuple[float, float] | None = None,
        profile: str | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: tuple[int, int, int, int] | None = None,
        rgbww_color: tuple[int, int, int, int, int] | None = None,
        transition: int | None = None,
        white: int | None = None,
        xy_color: tuple[float, float] | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Turns on one or more lights and adjusts their properties, even when they are turned on already.

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
        flash: LightFlash | None = None,
        transition: int | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Turns off one or more lights.

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
        flash: LightFlash | None = None,
        hs_color: tuple[float, float] | None = None,
        profile: str | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: tuple[int, int, int, int] | None = None,
        rgbww_color: tuple[int, int, int, int, int] | None = None,
        transition: int | None = None,
        white: int | None = None,
        xy_color: tuple[float, float] | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Toggles one or more lights, from on to off, or off to on, based on their current state.

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
        flash: LightFlash | None = None,
        hs_color: tuple[float, float] | None = None,
        profile: str | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: tuple[int, int, int, int] | None = None,
        rgbww_color: tuple[int, int, int, int, int] | None = None,
        transition: int | None = None,
        white: int | None = None,
        xy_color: tuple[float, float] | None = None,
    ) -> None:
        """Turns on one or more lights and adjusts their properties, even when they are turned on already.

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
        flash: LightFlash | None = None,
        transition: int | None = None,
    ) -> None:
        """Turns off one or more lights.

        Args:
            flash: Tell light to flash, can be either value short or long.
            transition: Duration it takes to get to next state.
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
        flash: LightFlash | None = None,
        hs_color: tuple[float, float] | None = None,
        profile: str | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: tuple[int, int, int, int] | None = None,
        rgbww_color: tuple[int, int, int, int, int] | None = None,
        transition: int | None = None,
        white: int | None = None,
        xy_color: tuple[float, float] | None = None,
    ) -> None:
        """Toggles one or more lights, from on to off, or off to on, based on their current state.

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
