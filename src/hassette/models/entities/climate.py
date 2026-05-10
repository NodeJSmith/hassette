from hassette.models.states import ClimateState
from hassette.models.states.climate import ClimateAttributes

from .base import BaseEntity


class ClimateEntity(BaseEntity[ClimateState, str]):
    @property
    def attributes(self) -> ClimateAttributes:
        return self.state.attributes

    async def set_preset_mode(
        self,
        *,
        preset_mode: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_preset_mode",
            target={"entity_id": self.entity_id},
            preset_mode=preset_mode,
        )

    async def set_temperature(
        self,
        *,
        hvac_mode: str | None = None,
        target_temp_high: float | None = None,
        target_temp_low: float | None = None,
        temperature: float | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_temperature",
            target={"entity_id": self.entity_id},
            hvac_mode=hvac_mode,
            target_temp_high=target_temp_high,
            target_temp_low=target_temp_low,
            temperature=temperature,
        )

    async def set_humidity(
        self,
        *,
        humidity: int,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_humidity",
            target={"entity_id": self.entity_id},
            humidity=humidity,
        )

    async def set_fan_mode(
        self,
        *,
        fan_mode: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_fan_mode",
            target={"entity_id": self.entity_id},
            fan_mode=fan_mode,
        )

    async def set_hvac_mode(
        self,
        *,
        hvac_mode: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_hvac_mode",
            target={"entity_id": self.entity_id},
            hvac_mode=hvac_mode,
        )

    async def set_swing_mode(
        self,
        *,
        swing_mode: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_swing_mode",
            target={"entity_id": self.entity_id},
            swing_mode=swing_mode,
        )

    async def set_swing_horizontal_mode(
        self,
        *,
        swing_horizontal_mode: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_swing_horizontal_mode",
            target={"entity_id": self.entity_id},
            swing_horizontal_mode=swing_horizontal_mode,
        )

    async def turn_on(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    async def turn_off(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    async def toggle(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )
