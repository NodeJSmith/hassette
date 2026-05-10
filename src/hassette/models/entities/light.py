from typing import Any, Literal

from hassette.const.colors import Color
from hassette.models.states import LightState
from hassette.models.states.light import LightAttributes

from .base import BaseEntity

Flash = Literal["long", "short"]


class LightEntity(BaseEntity[LightState, str]):
    @property
    def attributes(self) -> LightAttributes:
        return self.state.attributes

    async def turn_on(
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
        await self.api.call_service(
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

    async def turn_off(
        self,
        *,
        flash: Literal["long", "short"] | None = None,
        transition: int | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
            flash=flash,
            transition=transition,
        )

    async def toggle(
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
        await self.api.call_service(
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
