from hassette.const.colors import Color
from hassette.models.states import LightState

from .base import BaseEntity


class LightEntity(BaseEntity[LightState]):
    async def turn_on(
        self,
        color_name: Color | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        rgbw_color: tuple[int, int, int, int] | None = None,
        rgbww_color: tuple[int, int, int, int, int] | None = None,
        xy_color: tuple[float, float] | None = None,
        hs_color: tuple[float, float] | None = None,
        color_temp_kelvin: int | None = None,
        min_color_temp_kelvin: int | None = None,
        max_color_temp_kelvin: int | None = None,
        white: int | None = None,
        **data,
    ):
        """Turn on the light with optional color."""
        return await self.api.turn_on(
            self.entity_id,
            self.domain,
            color_name=color_name,
            rgb_color=rgb_color,
            rgbw_color=rgbw_color,
            rgbww_color=rgbww_color,
            xy_color=xy_color,
            hs_color=hs_color,
            color_temp_kelvin=color_temp_kelvin,
            min_color_temp_kelvin=min_color_temp_kelvin,
            max_color_temp_kelvin=max_color_temp_kelvin,
            white=white,
            **data,
        )
