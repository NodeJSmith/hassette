from typing import Literal

from hassette.const.colors import Color
from hassette.models.states import LightState
from hassette.models.states.light import LightAttributes

from .base import BaseEntity

Flash = Literal["short", "long"]


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
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: tuple[int, int, int, int] | None = None,
        rgbww_color: tuple[int, int, int, int, int] | None = None,
        xy_color: tuple[float, float] | None = None,
        hs_color: tuple[float, float] | None = None,
        color_temp_kelvin: int | None = None,
        white: int | None = None,
        transition: float | None = None,
        flash: Flash | None = None,
        effect: str | None = None,
        profile: str | None = None,
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
            rgb_color=rgb_color,
            rgbw_color=rgbw_color,
            rgbww_color=rgbww_color,
            xy_color=xy_color,
            hs_color=hs_color,
            color_temp_kelvin=color_temp_kelvin,
            white=white,
            transition=transition,
            flash=flash,
            effect=effect,
            profile=profile,
        )

    async def turn_off(self, *, transition: float | None = None, flash: Flash | None = None) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
            transition=transition,
            flash=flash,
        )

    async def toggle(
        self,
        *,
        brightness: int | None = None,
        brightness_pct: int | None = None,
        color_name: Color | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: tuple[int, int, int, int] | None = None,
        rgbww_color: tuple[int, int, int, int, int] | None = None,
        xy_color: tuple[float, float] | None = None,
        hs_color: tuple[float, float] | None = None,
        color_temp_kelvin: int | None = None,
        white: int | None = None,
        transition: float | None = None,
        flash: Flash | None = None,
        effect: str | None = None,
        profile: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
            brightness=brightness,
            brightness_pct=brightness_pct,
            color_name=color_name,
            rgb_color=rgb_color,
            rgbw_color=rgbw_color,
            rgbww_color=rgbww_color,
            xy_color=xy_color,
            hs_color=hs_color,
            color_temp_kelvin=color_temp_kelvin,
            white=white,
            transition=transition,
            flash=flash,
            effect=effect,
            profile=profile,
        )
